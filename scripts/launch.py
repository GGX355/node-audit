"""PyInstaller 入口。不要用包内 __main__.py：相对 import 在 -F 打包后不可靠。"""
import sys

from node_audit.cli import main

if __name__ == "__main__":
    sys.exit(main())
