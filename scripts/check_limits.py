"""Fail when a Python file or function grows past the project's size limits.

Usage: python scripts/check_limits.py [--file-lines N] [--function-lines N] PATH...
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path


def function_spans(tree: ast.AST) -> Iterator[tuple[str, int, int]]:
    """Yield (name, first line, line count) for every function and method."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            last = node.end_lineno or node.lineno
            yield node.name, node.lineno, last - node.lineno + 1


def check_file(path: Path, file_limit: int, function_limit: int) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    total = len(text.splitlines())
    if total > file_limit:
        problems.append(f"{path}: {total} lines (limit {file_limit})")
    for name, start, length in function_spans(ast.parse(text, filename=str(path))):
        if length > function_limit:
            problems.append(f"{path}:{start}: {name}() has {length} lines (limit {function_limit})")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("src"), Path("tests")])
    parser.add_argument("--file-lines", type=int, default=500)
    parser.add_argument("--function-lines", type=int, default=50)
    args = parser.parse_args(argv)
    files = sorted({f for root in args.paths for f in root.rglob("*.py")})
    problems = [p for f in files for p in check_file(f, args.file_lines, args.function_lines)]
    print("\n".join(problems) if problems else f"size limits ok ({len(files)} files)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
