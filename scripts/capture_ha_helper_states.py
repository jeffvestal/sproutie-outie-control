#!/usr/bin/env python3
"""Capture the current Home Assistant input-helper values without credentials."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path


def helper_states(states: list[dict]) -> dict[str, str]:
    """Return only input-helper state values, never API metadata or credentials."""
    return {
        state["entity_id"]: state["state"]
        for state in states
        if state.get("entity_id", "").startswith("input_") and "state" in state
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    base_url = os.environ["HA_URL"].rstrip("/")
    token = os.environ["HA_ACCESS_TOKEN"]
    request = urllib.request.Request(
        f"{base_url}/api/states", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        states = json.load(response)
    captured = helper_states(states)
    args.destination.write_text(json.dumps(captured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"captured_helpers={len(captured)} destination={args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
