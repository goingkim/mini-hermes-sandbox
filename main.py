from __future__ import annotations

import sys

from mini_hermes.cli import main as mini_hermes_main


if __name__ == "__main__":
    args = sys.argv[1:] or ["chat"]
    mini_hermes_main(args)
