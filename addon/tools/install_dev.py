r"""Copies the working files into Interface\AddOns\NoctisLootCouncilDev, a second copy of
the addon for testing in game next to an installed release, with its own saved file
(NoctisLootCouncilDev.lua).

    python addon/tools/install_dev.py "<WoW>\_forever_"

The .toc files are renamed to match the folder and titled "Noctis Loot Council (dev)".
Enable only one copy at a time: a second copy stays off and says so.
Close the game first if you added a file or changed a .toc; otherwise /reload is enough.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the addon folder
REPO = os.path.dirname(ROOT)
TOCS = ["NoctisLootCouncil.toc", "NoctisLootCouncil_Camelot.toc"]
# Files shipped that the .toc doesn't list: name in the addon -> source.
EXTRA = {"LICENSE": os.path.join(REPO, "LICENSE")}  # add media/icon.tga etc. once there is artwork


def toc_files(text):
    return [line.strip().replace("\\", "/") for line in text.splitlines()
            if line.strip() and not line.startswith("#")]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    addons = os.path.join(sys.argv[1], "Interface", "AddOns")
    if not os.path.isdir(addons):
        sys.exit("install_dev: no Interface/AddOns folder in " + sys.argv[1])
    dev = os.path.join(addons, "NoctisLootCouncilDev")
    if os.path.islink(dev) or (os.path.isdir(dev) and os.path.realpath(dev) != os.path.abspath(dev)):
        sys.exit("install_dev: " + dev + " is a link; remove it first")
    os.makedirs(dev, exist_ok=True)

    with open(os.path.join(ROOT, TOCS[0]), encoding="utf-8") as f:
        toc = f.read()
    for name in TOCS:
        target = os.path.join(dev, name.replace("NoctisLootCouncil", "NoctisLootCouncilDev", 1))
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(toc.replace("## Title: Noctis Loot Council", "## Title: Noctis Loot Council (dev)", 1)
                    .replace("AddOns\\NoctisLootCouncil\\", "AddOns\\NoctisLootCouncilDev\\"))
    sources = [(name, os.path.join(ROOT, name)) for name in toc_files(toc)] + list(EXTRA.items())
    for name, source in sources:
        target = os.path.join(dev, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
    print("copied %d files to %s" % (len(sources) + len(TOCS), dev))


if __name__ == "__main__":
    main()
