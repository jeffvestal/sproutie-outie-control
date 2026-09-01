#!/usr/bin/env python3
"""Publish a secrets-scrubbed Home Assistant config archive from a protected staging copy."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


SENSITIVE_KEY = re.compile(
    r"(?:pass(?:word)?|token|secret|api[_-]?key|authorization|credential|"
    r"client[_-]?secret|refresh[_-]?token|access[_-]?token|bearer|cookie|username|email)",
    re.IGNORECASE,
)
SENSITIVE_FILES = {
    ".storage/auth",
    ".storage/auth_provider.homeassistant",
    ".storage/http.auth",
    ".storage/application_credentials",
}
BINARY_OR_STATE_SUFFIXES = {".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3", ".pyc"}
TEXT_SUFFIXES = {"", ".yaml", ".yml", ".json", ".log", ".txt", ".conf", ".py", ".sh", ".md", ".xml", ".js"}
URL_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")


def is_sensitive_path(relative: Path) -> bool:
    value = relative.as_posix()
    if value in SENSITIVE_FILES or value.startswith(".storage/google."):
        return True
    lower_name = relative.name.lower()
    return "secret" in lower_name or lower_name.endswith((".key", ".pem"))


def is_binary_or_state(relative: Path) -> bool:
    return any(relative.name.endswith(suffix) for suffix in BINARY_OR_STATE_SUFFIXES)


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "<redacted>" if SENSITIVE_KEY.search(str(key)) else redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    lines = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"^(\s*[^#\n][^:\n]*?(?:password|token|secret|api[_-]?key|authorization|credential|client[_-]?secret|username|email)[^:\n]*:\s*).*$", line, re.IGNORECASE)
        if match:
            ending = "\n" if line.endswith("\n") else ""
            lines.append(f"{match.group(1)}<redacted>{ending}")
        else:
            lines.append(line)
    result = "".join(lines)
    result = URL_CREDENTIALS.sub(r"\1<redacted>@", result)
    result = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s'\"]+", r"\1<redacted>", result)
    result = re.sub(r"(?i)([?&](?:token|api_key|access_token)=)[^&\s'\"]+", r"\1<redacted>", result)
    return result


def copy_scrubbed(source: Path, destination: Path) -> tuple[int, int]:
    copied = skipped = 0
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            continue
        if is_sensitive_path(relative) or is_binary_or_state(relative):
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(json.dumps(redact_value(json.loads(path.read_text(encoding="utf-8"))), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            copied += 1
            continue
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        if path.suffix.lower() in TEXT_SUFFIXES or not path.suffix:
            try:
                target.write_text(redact_text(path.read_text(encoding="utf-8")), encoding="utf-8")
                copied += 1
                continue
            except UnicodeDecodeError:
                pass
        shutil.copy2(path, target)
        copied += 1
    return copied, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="protected raw staging directory")
    parser.add_argument("destination", type=Path, help="published, scrubbed archive directory")
    args = parser.parse_args(argv)
    if not args.source.is_dir():
        parser.error(f"source is not a directory: {args.source}")
    if args.destination.exists():
        parser.error(f"destination already exists: {args.destination}")
    args.destination.mkdir(parents=True)
    copied, skipped = copy_scrubbed(args.source, args.destination)
    (args.destination / "REDACTION.md").write_text(
        "This is a read-only forensic archive of the running HA config.\n\n"
        "Excluded: direct secret/auth stores, private keys, and recorder databases.\n"
        "JSON sensitive-key values and likely sensitive text-line values are replaced with `<redacted>`.\n"
        f"Published files: {copied}; excluded files: {skipped}.\n",
        encoding="utf-8",
    )
    print(f"published={copied} excluded={skipped} destination={args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
