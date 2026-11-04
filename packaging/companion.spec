# PyInstaller spec for the officers' single-file companion app.
# Build on Windows from the project folder:
#   python -m pip install -r requirements-dev.txt
#   python tools/package.py companion
# The result is dist/NoctisLootCompanion.exe, a windowed app (no console). companion.ini and companion.log
# are created next to it. Releases are built by .github/workflows/companion-release.yml, not by hand.
import os
import re

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
COMPANION = os.path.join(ROOT, "companion")
ASSETS = os.path.join(COMPANION, "assets")

# The version in the .exe's Properties > Details, from companion/__init__.py.
with open(os.path.join(COMPANION, "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', f.read()).groups()
NUMBERS = ", ".join(VERSION) + ", 0"
DOTTED = ".".join(VERSION)
VERSION_FILE = os.path.join(workpath, "version_info.txt")
os.makedirs(workpath, exist_ok=True)
with open(VERSION_FILE, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({NUMBERS}), prodvers=({NUMBERS})),
  kids=[StringFileInfo([StringTable("040904B0", [
    StringStruct("CompanyName", "Noctis"),
    StringStruct("FileDescription", "Noctis Loot companion app"),
    StringStruct("FileVersion", "{DOTTED}"),
    StringStruct("ProductName", "Noctis Loot companion"),
    StringStruct("ProductVersion", "{DOTTED}"),
    StringStruct("OriginalFilename", "NoctisLootCompanion.exe")])]),
    VarFileInfo([VarStruct("Translation", [1033, 1200])])]
)
""")

a = Analysis(
    [os.path.join(SPECPATH, "companion_entry.py")],
    pathex=[ROOT],
    binaries=[],
    # The window's page and what it shows, read from beside companion/ui.py.
    datas=[
        (os.path.join(COMPANION, "page.html"), "companion"),
        (os.path.join(ASSETS, "owl.png"), "companion/assets"),
        (os.path.join(ASSETS, "Philosopher-Bold.ttf"), "companion/assets"),
        (os.path.join(ASSETS, "Philosopher-OFL.txt"), "companion/assets"),
    ],
    hiddenimports=["companion.ui"],  # imported inside main(), so the window can be missing from source
    hookspath=[],
    runtime_hooks=[],
    # Keep the bot's dependencies out: the companion needs only the standard library and the window's three.
    excludes=["discord", "aiohttp", "dotenv", "bot", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NoctisLootCompanion",
    icon=os.path.join(ASSETS, "owl.ico"),
    version=VERSION_FILE,
    debug=False,
    strip=False,
    upx=False,
    console=False,  # a window and a tray icon; --console needs `python -m companion` from the code
)
