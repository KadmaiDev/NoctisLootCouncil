r"""Builds what each kind of user downloads, into dist/:

    python tools/package.py addon        NoctisLootCouncil-<version>.zip, for CurseForge (everyone in the raid)
    python tools/package.py companion    NoctisLootCompanion.exe, for officers (Windows; needs PyInstaller)
    python tools/package.py all          both

The bot isn't packaged here: the server builds it from the repo with `docker compose up -d --build`
(README, "Setting up the bot").

The addon zip holds one folder, NoctisLootCouncil, with the two .toc files, the files they list
and the LICENSE, which is what CurseForge expects. Its version is the .toc's `## Version:`.
"""
import os
import re
import subprocess
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(REPO, "addon")
DIST = os.path.join(REPO, "dist")
NAME = "NoctisLootCouncil"
TOCS = [NAME + ".toc", NAME + "_Camelot.toc"]
EXTRA = {"LICENSE": os.path.join(REPO, "LICENSE")}  # name in the addon -> source


def toc_text():
    with open(os.path.join(ADDON, TOCS[0]), encoding="utf-8") as f:
        return f.read()


def addon_version():
    m = re.search(r"^## Version:\s*(\S+)", toc_text(), re.M)
    if not m:
        sys.exit("package: no ## Version: in " + TOCS[0])
    return m.group(1)


def addon_files():
    """(name in the zip's addon folder, source path) for everything shipped."""
    listed = [line.strip().replace("\\", "/") for line in toc_text().splitlines()
              if line.strip() and not line.startswith("#")]
    files = [(name, os.path.join(ADDON, name)) for name in TOCS + listed] + list(EXTRA.items())
    missing = [name for name, path in files if not os.path.isfile(path)]
    if missing:
        sys.exit("package: missing " + ", ".join(missing))
    return files


def package_addon():
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "%s-%s.zip" % (NAME, addon_version()))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, path in addon_files():
            z.write(path, NAME + "/" + name)
    print("addon: " + out)
    return out


def package_companion():
    spec = os.path.join(REPO, "packaging", "companion.spec")
    build = os.path.join(REPO, "build")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", DIST,
                    "--workpath", build, spec], cwd=REPO, check=True)
    out = os.path.join(DIST, "NoctisLootCompanion.exe" if os.name == "nt" else "NoctisLootCompanion")
    print("companion: " + out)
    return out


def main():
    what = sys.argv[1] if len(sys.argv) == 2 else None
    if what not in ("addon", "companion", "all"):
        sys.exit(__doc__)
    if what in ("addon", "all"):
        package_addon()
    if what in ("companion", "all"):
        package_companion()


if __name__ == "__main__":
    main()
