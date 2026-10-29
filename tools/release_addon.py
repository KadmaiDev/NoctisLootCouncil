r"""Builds the addon's CurseForge zip and, with --upload, publishes it.

    python tools/release_addon.py               run the addon's tests and build dist/NoctisLootCouncil-<version>.zip
    python tools/release_addon.py --upload      also upload it to CurseForge as a RELEASE_TYPE file, then tag
                                                addon-v<version> and make a GitHub release with the same zip
    python tools/release_addon.py --github      build, then only the GitHub part
    python tools/release_addon.py --versions    list CurseForge's WoW Forever game versions (to set
                                                GAME_VERSIONS when the client moves on)

Publishing needs everything committed and pushed, so the tag matches the zip, and the first heading of
addon/CHANGELOG.md must be "## Noctis Loot Council <version>"; that section is the release's notes.
Uploading also needs PROJECT_ID, from the project the owner creates on CurseForge.

The zip is tools/package.py's: the .toc files, the .lua files they list, the LICENSE and the icon.
CurseForge rejects runnable files such as scripts, so anything else stops the build.
The tests run with `luajit` (or the LUAJIT environment variable).
The CurseForge token comes from the CURSE_API_KEY environment variable (or the Windows user
environment) and is never printed.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

import package

PROJECT_ID = None  # set once the owner has created the project on CurseForge
API = "https://wow.curseforge.com/api"
GAME_VERSIONS = [17053]  # WoW Forever 1.60.1; at launch, find the live one with --versions
FOREVER_TYPE = 88568  # CurseForge's game version type for WoW Forever
RELEASE_TYPE = "beta"  # "release", "beta" or "alpha": beta until it has run in a real raid
CHANGELOG = os.path.join(package.ADDON, "CHANGELOG.md")
TITLE = "Noctis Loot Council"


def fail(msg):
    sys.exit("release_addon: " + msg)


def run(*args):
    r = subprocess.run(args, cwd=package.REPO, capture_output=True, text=True)
    if r.returncode != 0:
        fail("%s failed: %s" % (" ".join(args[:3]), (r.stderr or r.stdout).strip()[:1000]))
    return r.stdout.strip()


def check_pushed():
    if run("git", "status", "--porcelain", "--untracked-files=no"):
        fail("commit your changes first; the release must match a pushed commit")
    run("git", "fetch", "-q", "origin")
    if run("git", "rev-parse", "HEAD") != run("git", "rev-parse", "@{u}"):
        fail("push first; HEAD isn't on the remote branch")


def build():
    tocs = [open(os.path.join(package.ADDON, toc), encoding="utf-8").read() for toc in package.TOCS]
    if tocs[0] != tocs[1]:
        fail("the two .toc files differ")
    tests = subprocess.run([os.environ.get("LUAJIT", "luajit"), "tests/run.lua"], cwd=package.ADDON,
                           capture_output=True, text=True)
    last = tests.stdout.strip().splitlines()[-1:] or [""]
    if tests.returncode != 0 or not last[0].endswith(" 0 failed"):
        fail("tests failed:\n" + tests.stdout[-2000:])
    for name, _ in package.addon_files():
        if name not in package.EXTRA and not name.endswith((".toc", ".lua")):
            fail("refusing to ship " + name)
    return package.package_addon(), package.addon_version()


def notes(ver):
    """This version's section of the changelog. Its first heading must be this version, so a draft
    ("not yet released") or a forgotten version bump never goes out."""
    with open(CHANGELOG, encoding="utf-8") as f:
        lines = f.read().splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    if not starts or lines[starts[0]].strip() != "## %s %s" % (TITLE, ver):
        fail("addon/CHANGELOG.md's first heading must be '## %s %s'" % (TITLE, ver))
    end = starts[1] if len(starts) > 1 else len(lines)
    return "\n".join(lines[starts[0] + 1:end]).strip() + "\n"


def token():
    key = os.environ.get("CURSE_API_KEY")
    if not key and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = winreg.QueryValueEx(k, "CURSE_API_KEY")[0]
        except OSError:
            key = None
    if not key:
        fail("CURSE_API_KEY is not set")
    return key


def list_versions():
    req = urllib.request.Request(API + "/game/versions", headers={"X-Api-Token": token()})
    try:
        with urllib.request.urlopen(req) as r:
            versions = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        fail("listing versions failed: HTTP %d" % e.code)
    for v in sorted((v for v in versions if v.get("gameVersionTypeID") == FOREVER_TYPE), key=lambda v: v["id"]):
        print("%6d  %s%s" % (v["id"], v.get("name"), "   <- in use" if v["id"] in GAME_VERSIONS else ""))


def upload(path, ver, text):
    metadata = {
        "changelog": text,
        "changelogType": "markdown",
        "displayName": "%s %s" % (TITLE, ver),
        "gameVersions": GAME_VERSIONS,
        "releaseType": RELEASE_TYPE,
    }
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    body = b"".join([
        ("--%s\r\nContent-Disposition: form-data; name=\"metadata\"\r\n"
         "Content-Type: application/json\r\n\r\n" % boundary).encode(),
        json.dumps(metadata).encode(), b"\r\n",
        ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
         "Content-Type: application/zip\r\n\r\n" % (boundary, os.path.basename(path))).encode(),
        data, b"\r\n",
        ("--%s--\r\n" % boundary).encode(),
    ])
    req = urllib.request.Request(
        "%s/projects/%d/upload-file" % (API, PROJECT_ID), data=body, method="POST",
        headers={"X-Api-Token": token(), "Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(req) as r:
            print("uploaded: HTTP %d %s" % (r.status, r.read().decode()))
    except urllib.error.HTTPError as e:
        fail("upload failed: HTTP %d %s" % (e.code, e.read().decode()[:1000]))


def github_release(path, ver, text):
    tag = "addon-v" + ver  # the companion's releases are companion-v*
    head = run("git", "rev-parse", "HEAD")
    if run("git", "tag", "--list", tag):
        if run("git", "rev-parse", tag + "^{commit}") != head:
            fail("tag %s already exists on a different commit" % tag)
    else:
        run("git", "tag", "-a", tag, "-m", "%s %s" % (TITLE, ver))
    run("git", "push", "-q", "origin", tag)
    if subprocess.run(["gh", "release", "view", tag], cwd=package.REPO, capture_output=True).returncode == 0:
        fail("GitHub release %s already exists; not replacing it" % tag)
    notes_file = os.path.join(package.DIST, "addon-notes.md")
    with open(notes_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    # --latest=false: the README's "latest release" link is the companion's .exe.
    args = ["gh", "release", "create", tag, path, "--title", "%s %s" % (TITLE, ver),
            "--notes-file", notes_file, "--verify-tag", "--latest=false"]
    if RELEASE_TYPE != "release":
        args.append("--prerelease")
    print("github release: " + run(*args))


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else None
    if mode not in (None, "--upload", "--github", "--versions"):
        sys.exit(__doc__)
    if mode == "--versions":
        return list_versions()
    if mode == "--upload" and not PROJECT_ID:
        fail("no CurseForge project yet: set PROJECT_ID once the owner has created it")
    if mode:
        check_pushed()
    path, ver = build()
    if mode:
        text = notes(ver)
        if mode == "--upload":
            upload(path, ver, text)
        github_release(path, ver, text)


if __name__ == "__main__":
    main()
