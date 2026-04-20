#!/usr/bin/env python3
"""Fail if tracked files contain patterns that look like real API keys.

Used in CI and optionally via pre-commit. Intended catches:
  - OpenRouter keys (sk-or-v1- + long hex)
  - Other common ``sk-...`` secret shapes when clearly not test placeholders

Safe substrings (ignored when they appear on the same line): REDACTED, PLACEHOLDER,
example.com, sk-or-test, sk-x (short test vectors in unit tests).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Skip likely-binary or huge artifacts; secrets should not live here anyway.
_SKIP_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".gz",
        ".zip",
        ".tar",
        ".parquet",
        ".pkl",
        ".bin",
        ".sqlite3",
        ".pdf",
        ".so",
        ".dylib",
        ".dll",
        ".pyc",
        ".pyo",
    }
)


def _git_ls_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=off", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    raw = proc.stdout.decode("utf-8", errors="replace")
    return [REPO_ROOT / p for p in raw.split("\0") if p]


def _should_skip_path(path: Path) -> bool:
    try:
        rel = path.relative_to(REPO_ROOT)
    except ValueError:
        return True
    parts = rel.parts
    if any(p in {".git", "__pycache__", ".venv", "node_modules"} for p in parts):
        return True
    lower = path.name.lower()
    return any(lower.endswith(s) for s in _SKIP_SUFFIXES)


def _line_looks_safe(line: str) -> bool:
    lowered = line.lower()
    if "redacted" in lowered or "placeholder" in lowered:
        return True
    if "example.com" in lowered or "example.org" in lowered:
        return True
    if "sk-or-test" in line:
        return True
    if "test-from-dotenv" in line:
        return True
    # Unit tests use OPENROUTER_API_KEY=sk-x in generated env file bodies.
    if re.search(r"(?:^|[^0-9A-Za-z])sk-x(?:[^0-9A-Za-z]|$)", line):
        return True
    return False


# OpenRouter: sk-or-v1- + hex payload (real keys are long hex; placeholders use REDACTED...).
_OPENROUTER_HEX = re.compile(r"sk-or-v1-[0-9a-f]{32,}", re.IGNORECASE)

# Other providers — long random-looking suffixes only (reduce doc false positives).
_OPENAI_PROJ = re.compile(r"sk-proj-[A-Za-z0-9_-]{48,}")
_ANTHROPIC = re.compile(r"sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{40,}")


def _violations_in_line(line: str, line_no: int) -> list[str]:
    if _line_looks_safe(line):
        return []
    out: list[str] = []
    if _OPENROUTER_HEX.search(line):
        out.append(f"line {line_no}: possible OpenRouter API key (sk-or-v1- + hex)")
    if _OPENAI_PROJ.search(line):
        out.append(f"line {line_no}: possible OpenAI project API key (sk-proj-...)")
    if _ANTHROPIC.search(line):
        out.append(f"line {line_no}: possible Anthropic API key (sk-ant-...)")
    return out


def scan_file(path: Path) -> list[str]:
    rel = path.relative_to(REPO_ROOT)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except UnicodeDecodeError:
        return []

    issues: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for msg in _violations_in_line(line, i):
            issues.append(f"{rel}: {msg}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="If set, only these paths are scanned (pre-commit mode). Default: git ls-files.",
    )
    args = parser.parse_args()

    if args.paths:
        candidates = [Path(p).resolve() for p in args.paths]
    else:
        candidates = _git_ls_files()
        if not candidates:
            print(
                "check_no_leaked_secrets: no files from git ls-files; are you in a git repo?",
                file=sys.stderr,
            )
            return 1

    all_issues: list[str] = []
    for path in candidates:
        if not path.is_file() or _should_skip_path(path):
            continue
        try:
            path.relative_to(REPO_ROOT)
        except ValueError:
            continue
        all_issues.extend(scan_file(path))

    if all_issues:
        print("Possible leaked API key material:\n", file=sys.stderr)
        for item in all_issues:
            print(item, file=sys.stderr)
        hint = (
            "\nUse placeholders (e.g. sk-or-v1-REDACTED_USE_ENV) or keep secrets in untracked .env."
        )
        print(hint, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
