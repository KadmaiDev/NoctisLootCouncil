r"""Builds what each kind of user downloads, into dist/:

    python tools/package.py addon        NoctisLootCouncil-<version>.zip, for CurseForge (everyone in the raid)
    python tools/package.py companion    NoctisLootCompanion.exe, for officers (Windows; needs PyInstaller)
    python tools/package.py bot          NoctisLootBot.zip, for the server (Docker builds it there)
    python tools/package.py all          all three

The addon zip holds one folder, NoctisLootCouncil, with the two .toc files, the files they list
and the LICENSE, which is what CurseForge expects. Its version is the .toc's `## Version:`.

The bot zip holds one folder, NoctisLootBot: what `docker compose up -d --build` needs, the
.env.example and a README. It never holds a .env, so unpacking it over a running copy keeps
that copy's settings.
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
BOT = "NoctisLootBot"
BOT_FILES = {  # name in the bot folder -> source
    "Dockerfile": "Dockerfile",
    "docker-compose.yml": "docker-compose.yml",
    ".dockerignore": ".dockerignore",
    "requirements.txt": "requirements.txt",
    ".env.example": ".env.example",
    "LICENSE": "LICENSE",
    "README.txt": os.path.join("packaging", "bot-README.txt"),
}


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


def bot_files():
    """(name in the zip's bot folder, source path): BOT_FILES and the bot/ package's .py files."""
    files = [(name, os.path.join(REPO, src)) for name, src in BOT_FILES.items()]
    for folder, dirs, names in os.walk(os.path.join(REPO, "bot")):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(names):
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                files.append((os.path.relpath(path, REPO).replace("\\", "/"), path))
    missing = [name for name, path in files if not os.path.isfile(path)]
    if missing:
        sys.exit("package: missing " + ", ".join(missing))
    return files


def package_bot():
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, BOT + ".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, path in bot_files():
            z.write(path, BOT + "/" + name)
    print("bot: " + out)
    return out


def main():
    what = sys.argv[1] if len(sys.argv) == 2 else None
    if what not in ("addon", "companion", "bot", "all"):
        sys.exit(__doc__)
    if what in ("addon", "all"):
        package_addon()
    if what in ("companion", "all"):
        package_companion()
    if what in ("bot", "all"):
        package_bot()


if __name__ == "__main__":
    main()
