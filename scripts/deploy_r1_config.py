#!/usr/bin/env python3
"""Stage, Core-validate, and reversibly apply the R1 configuration.

The command receives HA credentials only from its environment. It preserves just the pairing
paths that R1 needs and never activates a configuration that has not passed the Core check.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ha"
COMPATIBILITY = (".storage", "custom_components/eufy_security", "www/snapshots")
REPLACED = ("configuration.yaml", "automations.yaml", "scenes.yaml", "scripts", "helpers", "dashboards", "template.yaml", "secrets.yaml")


def run(command, *, input_bytes=None, capture=False, cwd=None):
    return subprocess.run(command, input=input_bytes, check=True, capture_output=capture, cwd=cwd)


def ssh_prefix(args):
    return [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
        "-o", f"UserKnownHostsFile={args.known_hosts}", "-o", "StrictHostKeyChecking=yes",
        "-o", "IdentitiesOnly=yes", "-i", str(args.identity), f"{args.user}@{args.host}",
    ]


def remote(args, command, *, capture=False):
    return run(ssh_prefix(args) + [command], capture=capture)


def core_container(args):
    output = remote(args, "sudo -n docker ps --format '{{.Names}} {{.Image}}'", capture=True).stdout.decode()
    for line in output.splitlines():
        name, _, image = line.partition(" ")
        if "home-assistant" in image:
            return name
    raise RuntimeError("Core container not found. Disable Protection mode and restart the SSH add-on.")


def render_and_scan():
    run([sys.executable, str(REPO / "scripts" / "render_r1_role_scripts.py")], cwd=REPO)
    run([sys.executable, str(REPO / "scripts" / "secret_scan.py"), str(SOURCE)])


def source_tar():
    return run(["tar", "-C", str(SOURCE), "-cf", "-", "."], capture=True).stdout


def stage(args, stage_path, container):
    quoted_stage = shlex.quote(stage_path)
    remote(args, f"sudo -n rm -rf {quoted_stage} && sudo -n mkdir -p {quoted_stage}")
    run(ssh_prefix(args) + [f"sudo -n tar -C {quoted_stage} -xf -"], input_bytes=source_tar())
    for path in COMPATIBILITY:
        quoted_path = shlex.quote(path)
        remote(
            args,
            f"if sudo -n test -e /config/{quoted_path}; then sudo -n mkdir -p {quoted_stage}/$(dirname {quoted_path}) && sudo -n cp -a /config/{quoted_path} {quoted_stage}/{quoted_path}; fi",
        )
    # R1 has no credential-consuming configuration. Its active secrets file is deliberately empty.
    remote(args, f"sudo -n sh -c ': > {quoted_stage}/secrets.yaml && chmod 600 {quoted_stage}/secrets.yaml'")
    check = remote(
        args,
        f"sudo -n docker exec {shlex.quote(container)} python -m homeassistant --config {quoted_stage} --script check_config",
        capture=True,
    )
    report = (check.stdout + check.stderr).decode()
    print(report, end="")
    if "ERROR:" in report:
        raise RuntimeError("Core rejected the staged configuration")


def apply(args, stage_path):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rollback = f"/config/.r1-rollback-{stamp}"
    remote(args, f"sudo -n mkdir -p {shlex.quote(rollback)}")
    for path in REPLACED:
        quoted = shlex.quote(path)
        remote(args, f"if sudo -n test -e /config/{quoted}; then sudo -n cp -a /config/{quoted} {shlex.quote(rollback)}/{quoted}; fi")
    for path in REPLACED:
        quoted = shlex.quote(path)
        remote(args, f"sudo -n rm -rf /config/{quoted} && sudo -n cp -a {shlex.quote(stage_path)}/{quoted} /config/{quoted}")
    remote(args, "sudo -n docker restart $(sudo -n docker ps --format '{{.Names}} {{.Image}}' | awk '/home-assistant/ {print $1; exit}')")
    return rollback


def active_check(ha_url, token):
    request = Request(
        f"{ha_url.rstrip('/')}/api/config/core/check_config", method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, data=b"{}",
    )
    for attempt in range(12):
        try:
            with urlopen(request, timeout=30) as response:  # nosec B310 -- HA URL is operator supplied
                body = response.read().decode()
        except (HTTPError, URLError) as error:
            if attempt == 11:
                raise RuntimeError("Home Assistant did not become ready after Core restart") from error
            time.sleep(5)
            continue
        if "valid" not in body:
            raise RuntimeError("active REST configuration check did not report valid")
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--host", default="192.168.1.232")
    parser.add_argument("--user", default="kegsofduff")
    parser.add_argument("--identity", type=Path, default=Path.home() / ".ssh/id_ed25519")
    parser.add_argument("--known-hosts", type=Path, default=Path("/private/tmp/sproutie-ha-known-hosts"))
    parser.add_argument("--ha-url", default=os.environ.get("HA_URL", "http://192.168.1.232:8123"))
    parser.add_argument("--token", default=os.environ.get("HA_ACCESS_TOKEN"))
    args = parser.parse_args(argv)
    if args.activate and not args.token:
        parser.error("--activate requires HA_ACCESS_TOKEN or --token for read-only post-checks")
    render_and_scan()
    if not args.activate:
        print("R1 dry run passed. Activation retains: " + ", ".join(COMPATIBILITY))
        return 0
    container = core_container(args)
    stage_path = "/config/.r1-stage"
    try:
        stage(args, stage_path, container)
        rollback = apply(args, stage_path)
        active_check(args.ha_url, args.token)
        run([sys.executable, str(REPO / "scripts" / "verify_devices.py"), "--ha-url", args.ha_url, "--token", args.token])
    except Exception as error:
        print(f"Cutover stopped: {error}", file=sys.stderr)
        print("Do not retire v1; inspect the staged tree and use the captured rollback path if activation started.", file=sys.stderr)
        return 1
    print(f"R1 applied. Explicit rollback material: {rollback}")
    print("R1 is safety-disarmed. Complete the thermal/phone functional gate before arming or retiring v1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
