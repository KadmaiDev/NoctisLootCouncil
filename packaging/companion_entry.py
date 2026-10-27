"""Entry point for the single-file .exe (PyInstaller needs a script, not `python -m`)."""
import sys

from companion.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
