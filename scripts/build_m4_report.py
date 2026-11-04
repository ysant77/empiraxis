"""Print the M4 matched table from one or more matrix output folders."""

from __future__ import annotations

import sys
from pathlib import Path

from earthlab.harness.m4_report import collect, table


def main() -> int:
    folders = [Path(a) for a in sys.argv[1:]]
    if not folders:
        print("usage: build_m4_report.py <output folder> ...", file=sys.stderr)
        return 2
    print(table(collect(folders)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
