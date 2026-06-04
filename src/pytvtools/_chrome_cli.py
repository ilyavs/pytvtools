"""
CLI: print the Chrome launch command for the current platform.
"""
from pytvtools.chrome import Chrome


def main():
    print(Chrome.launch_command())
