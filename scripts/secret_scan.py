#!/usr/bin/env python3
"""Reject credential-looking literals from deployable R1 source files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


RULES = (
    ("bearer token", re.compile(r"authorization\s*:\s*bearer\s+(?![<$][A-Z_]+[>$])\S+", re.I)),
    ("inline password", re.compile(r"^\s*password\s*:\s*(?![!$]|\"\"|'')\S+", re.I)),
    ("inline API key", re.compile(r"^\s*(?:api[_-]?key|token)\s*:\s*(?![!$]|\"\"|'')\S+", re.I)),
    ("credential URL", re.compile(r"://[^\s/@:]+:[^\s/@]+@")),
)
SKIP = {"secrets.example.yaml"}


def findings(path: Path) -> list[str]:
    if path.name in SKIP:
        return []
    results: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for label, expression in RULES:
            if expression.search(line):
                results.append(f"{path}:{line_number}: {label}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    files = [file for path in args.paths for file in (path.rglob("*") if path.is_dir() else [path]) if file.is_file()]
    results = [finding for file in files for finding in findings(file)]
    if results:
        print("credential-looking source text found:", file=sys.stderr)
        print("\n".join(results), file=sys.stderr)
        return 1
    print(f"secret scan passed ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
