"""Static screen of a proposed patch, before any human or runner sees it. Nothing is applied.

The screen reads the unified diff as text. It blocks a patch that touches a path outside
the task, renames, copies, deletes, changes a file mode, adds a symlink or binary data,
edits pytest configuration, weakens a test, or adds a call that could reach the shell,
the network or the interpreter. A new Python file must parse, and may import only the
modules in ALLOWED_IMPORTS; obfuscated text and file or process access are blocked.

This is a filter in front of human review, not a sandbox. A pattern list cannot prove
code safe; the trusted isolated runner (docs/implementor-runner.md) and a human still
decide, and nothing here runs the code.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass

from earthlab.implement.contracts import (
    ImplementationResultV1,
    ImplementationTaskV1,
    ReviewFindingV1,
    Severity,
)

SCREEN_ID = "patch-screen-v1"
ALLOWED_IMPORTS = frozenset(
    {
        "__future__", "bisect", "collections", "dataclasses", "datetime", "enum",
        "functools", "itertools", "math", "numpy", "statistics", "typing", "zoneinfo",
    }
)  # fmt: skip
_IMPORT_LINE = re.compile(r"^\s*(?:from\s+(\S+)\s+import|import\s+([\w.]+))")
_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)$")
_STRUCTURAL = (
    ("rename from ", "rename"),
    ("copy from ", "copy"),
    ("deleted file mode", "delete"),
    ("old mode ", "mode_change"),
    ("new mode ", "mode_change"),
    ("GIT binary patch", "binary"),
    ("Binary files ", "binary"),
)
_TEST_CONFIG = frozenset({"conftest.py", "pytest.ini", "setup.cfg", "pyproject.toml", "tox.ini"})
# Added lines matching these are blocked. A pattern list cannot prove code safe; it only
# stops the obvious routes to the shell, network, interpreter and test bypass.
_UNSAFE: tuple[tuple[str, str], ...] = (
    ("shell", r"\b(subprocess|os\.system|os\.popen|os\.exec\w*|os\.spawn\w*|pty)\b"),
    ("network", r"\b(socket|urllib|requests|httpx|aiohttp|ftplib|smtplib|http\.client)\b"),
    ("dynamic_code", r"\b(eval|exec|compile|__import__)\s*\(|\bimportlib\b|\bctypes\b"),
    ("unsafe_load", r"\b(pickle|marshal|shelve|dill)\b"),
    ("filesystem", r"\b(shutil\.rmtree|os\.remove|os\.unlink|os\.rmdir|os\.chmod)\b"),
    ("environment", r"\bos\.environ\b|\bgetenv\s*\("),
    ("test_bypass", r"pytest\.(skip|xfail|importorskip)|mark\.(skip|skipif|xfail)|sys\.exit"),
    ("dynamic_code", r"\b(globals|locals|vars|setattr|delattr)\s*\(|__builtins__|sys\.modules"),
    ("obfuscation", r"\b(base64|codecs|zlib|binascii)\b|(\\x[0-9a-fA-F]{2}){4,}"),
    ("filesystem", r"\bopen\s*\(|\.write_(text|bytes)\s*\(|\btempfile\b|\bglob\b"),
    ("process", r"\b(threading|multiprocessing|signal|asyncio|atexit)\b"),
)
_UNSAFE_RE = tuple((check, re.compile(pattern)) for check, pattern in _UNSAFE)


@dataclass(frozen=True)
class FilePatch:
    path: str
    new_file: bool
    added: tuple[str, ...]
    header_lines: tuple[str, ...]


class PatchFormatError(ValueError):
    """The text is not a git unified diff the screen can read."""


def parse_patch(diff: str) -> list[FilePatch]:
    files: list[FilePatch] = []
    path: str | None = None
    new_file = False
    added: list[str] = []
    headers: list[str] = []
    in_hunk = False

    def close() -> None:
        if path is not None:
            files.append(FilePatch(path, new_file, tuple(added), tuple(headers)))

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            close()
            match = _HEADER.match(line)
            if match is None or match.group(1) != match.group(2):
                raise PatchFormatError(f"unreadable or renaming header: {line[:120]}")
            path, new_file, added, headers, in_hunk = match.group(1), False, [], [], False
            continue
        if path is None:
            if line.strip():
                raise PatchFormatError("text before the first diff header")
            continue
        if line.startswith("@@"):
            in_hunk = True
        elif not in_hunk:
            headers.append(line)
            new_file = new_file or line.startswith("new file mode")
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    close()
    if not files:
        raise PatchFormatError("no file in the patch")
    return files


def _finding(
    result: ImplementationResultV1, n: int, check: str, severity: Severity, msg: str, path: str
) -> ReviewFindingV1:
    return ReviewFindingV1(
        finding_id=f"{result.task_id}.screen.{n}",
        reviewer_kind="deterministic",
        reviewer_id=SCREEN_ID,
        artifact_sha256=result.artifact_sha256,
        check_id=check,
        severity=severity,
        message=msg[:500],
        path=path or None,
    )


def _imports(patch: FilePatch) -> Iterator[tuple[str, str]]:
    """Parse a new file and check its imports; for an edit, read import lines only."""
    if patch.new_file:
        try:
            tree = ast.parse("\n".join(patch.added), filename=patch.path)
        except SyntaxError as exc:
            yield "syntax_error", f"{patch.path}: {exc.msg} at line {exc.lineno}"
            return
        names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        names += [n.module or "." for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    else:
        names = [m.group(1) or m.group(2) for t in patch.added if (m := _IMPORT_LINE.match(t))]
    for name in names:
        if name.split(".")[0] not in ALLOWED_IMPORTS:
            yield "import_not_allowed", f"{patch.path} imports {name}"


def _problems(task: ImplementationTaskV1, patch: FilePatch) -> Iterator[tuple[str, str]]:
    if not patch.path.endswith(".py"):
        yield "file_type", f"{patch.path} is not a Python source file"
    if patch.path not in task.allowed_paths:
        yield "path_not_allowed", f"{patch.path} is not in the task's allowed paths"
    if patch.path.rsplit("/", 1)[-1] in _TEST_CONFIG:
        yield "test_config", f"{patch.path} can change how tests are collected"
    for line in patch.header_lines:
        if line.startswith("new file mode") and not line.endswith("100644"):
            yield "mode_change", f"{patch.path}: new file mode {line.split()[-1]}"
        for prefix, check in _STRUCTURAL:
            if line.startswith(prefix):
                yield check, f"{patch.path}: {line[:120]}"
    for number, text in enumerate(patch.added, start=1):
        if len(text) > 300:
            yield "obfuscation", f"{patch.path} added line {number} is {len(text)} characters"
        for check, pattern in _UNSAFE_RE:
            if pattern.search(text):
                yield check, f"{patch.path} added line {number}: {text.strip()[:160]}"
    if patch.path.endswith(".py"):
        yield from _imports(patch)


def screen_patch(
    task: ImplementationTaskV1, result: ImplementationResultV1
) -> tuple[ReviewFindingV1, ...]:
    """Blocking findings for every rule the patch breaks; empty when it passes the screen."""
    if result.status != "proposed":
        return ()
    try:
        patches = parse_patch(result.patch_diff)
    except PatchFormatError as exc:
        return (_finding(result, 1, "unreadable_patch", "blocking", str(exc), ""),)
    found = [
        (check, message, patch.path)
        for patch in patches
        for check, message in _problems(task, patch)
    ]
    return tuple(
        _finding(result, n, check, "blocking", message, path)
        for n, (check, message, path) in enumerate(found, start=1)
    )
