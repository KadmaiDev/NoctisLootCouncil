# PyInstaller spec for the officers' single-file companion app.
# Build on Windows from the project folder:
#   python -m pip install pyinstaller
#   python -m PyInstaller packaging/companion.spec
# The result is dist/NoctisLootCompanion.exe. companion.ini and companion.log are created next to it.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(SPECPATH, "companion_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # The companion uses the standard library only; keep the bot's dependencies out.
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
    debug=False,
    strip=False,
    upx=False,
    console=True,  # it's a console app: the first-run questions and the log are shown there
)
