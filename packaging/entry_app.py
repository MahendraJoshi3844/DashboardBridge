"""PyInstaller entry point for the t2pbi desktop app."""

from engines.t2pbi.desktop.shell import main

if __name__ == "__main__":
    raise SystemExit(main())
