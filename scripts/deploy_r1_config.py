#!/usr/bin/env python3
"""Compatibility stop for the retired drift-blind R1 cutover command."""

from __future__ import annotations

import sys


def main(_argv: list[str] | None = None) -> int:
    print(
        "scripts/deploy_r1_config.py is retired. Use scripts/deploy.sh --dry-run or make deploy; "
        "the old --activate path is intentionally unavailable.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
