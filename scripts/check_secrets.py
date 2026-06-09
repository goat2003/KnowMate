#!/usr/bin/env python3
"""Scan the repository for obvious committed secrets."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "venv",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".exe"}
PLACEHOLDER_WORDS = {
    "",
    "...",
    "<value>",
    "<secret>",
    "changeme",
    "change-me",
    "change-me-neo4j",
    "example",
    "fake",
    "placeholder",
    "rootpass",
    "apppass",
    "secret",
    "secret-token",
    "sk-secret",
    "plain-password",
}

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "assigned_secret",
        re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*(['\"])([^'\"]{12,})\1"),
    ),
]


def iter_tracked_files() -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return [path for path in ROOT.rglob("*") if path.is_file()]
    return [ROOT / line for line in output.splitlines() if line.strip()]


def should_scan(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in relative.parts):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return True


def looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    return (
        normalized in PLACEHOLDER_WORDS
        or normalized.startswith("${")
        or normalized.startswith("$env:")
        or normalized.startswith("env.")
        or normalized.endswith("_file")
    )


def scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[str] = []
    relative = path.relative_to(ROOT).as_posix()
    for line_number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(2) if name == "assigned_secret" else match.group(0)
                if name == "assigned_secret" and looks_like_placeholder(value):
                    continue
                findings.append(f"{relative}:{line_number}: {name}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="scan all tracked files; kept for CI readability")
    args = parser.parse_args()
    _ = args

    findings: list[str] = []
    for path in iter_tracked_files():
        if path.exists() and should_scan(path):
            findings.extend(scan_file(path))

    if findings:
        print("Potential committed secrets found:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print("secret scan ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
