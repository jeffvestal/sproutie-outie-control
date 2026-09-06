#!/usr/bin/env python3
"""Fail-closed Home Assistant deployment for the committed R1 configuration.

Dry runs read only remote path/hash inventory and the non-secret deployment ledger. A real
deployment is interactive, stages and Core-validates the candidate before changing active files,
refuses remote drift, and verifies a read-only sensor/device canary after activation.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ha"
SITE = REPO / "config" / "site.yaml"
MANAGED_ROOTS = (
    "configuration.yaml", "automations.yaml", "scenes.yaml", "template.yaml",
    "scripts", "helpers", "dashboards", "themes",
)
REMOTE_CONFIG = "/config"
STATE_ROOT = "/config/.sproutie-deploy"
LEDGER_PATH = f"{STATE_ROOT}/deployed.json"
SCHEMA = 1
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
HASH_LINE = re.compile(r"^([0-9a-f]{64})  (/.+)$")
UNAVAILABLE = {"", "none", "unknown", "unavailable"}


class DeployError(RuntimeError):
    """A fail-closed deployment stop."""


class DriftError(DeployError):
    """The remote managed tree no longer matches its recorded baseline."""


class CoreValidationError(DeployError):
    """Home Assistant rejected the staged candidate."""


class HAConfigLoader(yaml.SafeLoader):
    """Parse Home Assistant include tags for local syntax validation."""


def _construct_ha_tag(loader: yaml.Loader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


HAConfigLoader.add_multi_constructor("!", _construct_ha_tag)


@dataclass(frozen=True)
class Candidate:
    commit: str
    files: dict[str, str]
    archive: bytes
    canary_entity: str


@dataclass(frozen=True)
class FileChange:
    status: str
    path: str


@dataclass(frozen=True)
class Activation:
    kind: str
    services: tuple[tuple[str, str], ...]
    reason: str


@dataclass(frozen=True)
class Inspection:
    current: dict[str, str]
    ledger: dict[str, Any] | None
    desired_changes: tuple[FileChange, ...]
    remote_drift: tuple[FileChange, ...]
    baseline_error: str | None
    activation: Activation
    bootstrap_commit: str | None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise DeployError(f"unsafe managed path: {value!r}")
    if path.name.lower() == "secrets.yaml":
        raise DeployError("secrets.yaml is never a managed or transferred path")
    if path.parts[0] not in MANAGED_ROOTS:
        raise DeployError(f"path is outside the managed HA roots: {value}")


def validate_manifest(files: Mapping[str, str], *, allow_empty: bool = False) -> dict[str, str]:
    if not isinstance(files, Mapping):
        raise DeployError("manifest files must be a mapping")
    result: dict[str, str] = {}
    for path, digest in files.items():
        if not isinstance(path, str) or not isinstance(digest, str):
            raise DeployError("manifest paths and hashes must be strings")
        validate_relative_path(path)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise DeployError(f"invalid SHA-256 for {path}")
        result[path] = digest
    if not result and not allow_empty:
        raise DeployError("managed manifest is empty")
    return dict(sorted(result.items()))


def local_manifest(source: Path = SOURCE) -> dict[str, str]:
    files: dict[str, str] = {}
    for root_name in MANAGED_ROOTS:
        root = source / root_name
        if not root.exists():
            raise DeployError(f"required managed source is missing: {root}")
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if path.is_symlink():
                raise DeployError(f"deploy source may not contain symlinks: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            validate_relative_path(relative)
            files[relative] = sha256_bytes(path.read_bytes())
    return validate_manifest(files)


def build_archive(source: Path, files: Mapping[str, str]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for relative in sorted(files):
            validate_relative_path(relative)
            path = source / relative
            if not path.is_file() or path.is_symlink():
                raise DeployError(f"manifest member is no longer a regular file: {relative}")
            content = path.read_bytes()
            if sha256_bytes(content) != files[relative]:
                raise DeployError(f"source changed while the deployment archive was built: {relative}")
            info = tarfile.TarInfo(relative)
            info.size = len(content)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def diff_files(old: Mapping[str, str], new: Mapping[str, str]) -> tuple[FileChange, ...]:
    changes: list[FileChange] = []
    for path in sorted(set(old) | set(new)):
        if path not in old:
            changes.append(FileChange("A", path))
        elif path not in new:
            changes.append(FileChange("D", path))
        elif old[path] != new[path]:
            changes.append(FileChange("M", path))
    return tuple(changes)


def activation_for(changes: Sequence[FileChange]) -> Activation:
    paths = {change.path for change in changes}
    if not paths:
        return Activation("none", (), "managed files already match; no reload is needed")
    if any(path.split("/", 1)[0] in {"configuration.yaml", "helpers"} for path in paths):
        return Activation("restart", (("homeassistant", "restart"),), "configuration/helper changes require Core to rebuild integrations")
    service_by_root = {
        "automations.yaml": ("automation", "reload"),
        "scenes.yaml": ("scene", "reload"),
        "template.yaml": ("template", "reload"),
        "scripts": ("script", "reload"),
        "themes": ("frontend", "reload_themes"),
    }
    services = {service_by_root[root] for path in paths if (root := path.split("/", 1)[0]) in service_by_root}
    unknown = {path for path in paths if path.split("/", 1)[0] not in service_by_root and not path.startswith("dashboards/")}
    if unknown:
        return Activation("restart", (("homeassistant", "restart"),), "an unclassified managed change fails safe to a full restart")
    if len(services) > 1:
        return Activation("restart", (("homeassistant", "restart"),), "multiple domains changed; one restart avoids a partially reloaded mix")
    if services:
        service = next(iter(services))
        return Activation("targeted", (service,), f"only the {service[0]} domain changed")
    return Activation("none", (), "YAML-mode dashboard files changed; Core reads them without a domain reload")


def parse_ledger(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise DeployError("remote deployment ledger has an unsupported schema")
    allowed_keys = {
        "schema", "deployment_id", "commit", "files", "status", "activation",
        "rollback_id", "updated_at",
    }
    if set(payload) - allowed_keys:
        raise DeployError("remote deployment ledger contains unexpected fields")
    result = dict(payload)
    result["files"] = validate_manifest(payload.get("files", {}), allow_empty=True)
    commit = result.get("commit")
    if commit is not None and (not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise DeployError("remote deployment ledger has an invalid commit SHA")
    status = result.get("status")
    if status not in {"verified", "pending-verification", "untracked-baseline", "declared-bootstrap"}:
        raise DeployError("remote deployment ledger has an invalid status")
    for field in ("deployment_id", "rollback_id"):
        value = result.get(field)
        if value is not None and (not isinstance(value, str) or not SAFE_ID.fullmatch(value)):
            raise DeployError(f"remote deployment ledger has an invalid {field}")
    activation = result.get("activation")
    if activation is not None:
        if not isinstance(activation, dict) or set(activation) != {"kind", "reason"}:
            raise DeployError("remote deployment ledger has an invalid activation record")
        if activation.get("kind") not in {"none", "targeted", "restart"} or not isinstance(activation.get("reason"), str):
            raise DeployError("remote deployment ledger has an invalid activation record")
    if not isinstance(result.get("updated_at"), str):
        raise DeployError("remote deployment ledger has an invalid updated_at")
    return result


def inspect_remote(
    candidate: Candidate,
    transport: "SSHTransportProtocol",
    bootstrap_files: Mapping[str, str] | None = None,
    bootstrap_commit: str | None = None,
) -> Inspection:
    if bootstrap_commit is not None and not re.fullmatch(r"[0-9a-f]{40}", bootstrap_commit):
        raise DeployError("bootstrap commit must be a full lowercase SHA")
    current = validate_manifest(transport.inventory(REMOTE_CONFIG), allow_empty=True)
    raw_ledger = transport.read_json(LEDGER_PATH)
    ledger = parse_ledger(raw_ledger) if raw_ledger is not None else None
    remote_drift: tuple[FileChange, ...] = ()
    baseline_error: str | None = None
    if ledger is not None:
        remote_drift = diff_files(ledger["files"], current)
    elif current == candidate.files:
        pass
    elif bootstrap_files is not None:
        remote_drift = diff_files(validate_manifest(bootstrap_files, allow_empty=True), current)
    else:
        baseline_error = "remote ledger is missing and active files do not match the candidate; use --bootstrap-ref for a known prior commit or reconcile manually"
    desired = diff_files(current, candidate.files)
    return Inspection(current, ledger, desired, remote_drift, baseline_error, activation_for(desired), bootstrap_commit)


def assert_inspection_safe(inspection: Inspection) -> None:
    if inspection.baseline_error:
        raise DriftError(inspection.baseline_error)
    if inspection.remote_drift:
        paths = ", ".join(f"{change.status} {change.path}" for change in inspection.remote_drift)
        raise DriftError(f"remote drift detected against the recorded/declared baseline: {paths}")


def print_inspection(inspection: Inspection, output: Callable[[str], None] = print) -> None:
    output("Remote drift:")
    if inspection.baseline_error:
        output(f"  BLOCKED {inspection.baseline_error}")
    elif inspection.remote_drift:
        for change in inspection.remote_drift:
            output(f"  {change.status} {change.path}")
    else:
        output("  none")
    output("Candidate diff:")
    if inspection.desired_changes:
        for change in inspection.desired_changes:
            output(f"  {change.status} {change.path}")
    else:
        output("  none")
    output(f"Activation: {inspection.activation.kind} — {inspection.activation.reason}")


def git_output(args: Sequence[str], repo: Path = REPO) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout


def git_commit(repo: Path = REPO) -> str:
    commit = git_output(["rev-parse", "HEAD"], repo).decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise DeployError("git did not return a full commit SHA")
    return commit


def git_is_clean(repo: Path = REPO) -> bool:
    return not git_output(["status", "--porcelain", "--untracked-files=all"], repo).strip()


def manifest_from_git(ref: str, repo: Path = REPO) -> dict[str, str]:
    if not ref or ref.startswith("-"):
        raise DeployError("--bootstrap-ref must name a Git revision")
    try:
        data = git_output(["archive", "--format=tar", ref, "ha"], repo)
    except subprocess.CalledProcessError as error:
        raise DeployError(f"cannot read bootstrap Git ref {ref!r}") from error
    files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != "ha":
                raise DeployError("bootstrap archive escaped ha/")
            relative = PurePosixPath(*parts[1:]).as_posix()
            validate_relative_path(relative)
            source = archive.extractfile(member)
            if source is None:
                raise DeployError(f"cannot read bootstrap member: {member.name}")
            files[relative] = sha256_bytes(source.read())
    return validate_manifest(files)


def resolve_git_commit(ref: str, repo: Path = REPO) -> str:
    if not ref or ref.startswith("-"):
        raise DeployError("--bootstrap-ref must name a Git revision")
    try:
        commit = git_output(["rev-parse", f"{ref}^{{commit}}"], repo).decode().strip()
    except subprocess.CalledProcessError as error:
        raise DeployError(f"cannot resolve bootstrap Git ref {ref!r}") from error
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise DeployError("bootstrap Git ref did not resolve to a full commit SHA")
    return commit


def load_canary_entity(site: Path = SITE) -> str:
    with site.open(encoding="utf-8") as source:
        payload = yaml.safe_load(source)
    for zone in payload.get("site", {}).get("zones", {}).values():
        if zone.get("enabled", True):
            entity = zone.get("ha", {}).get("telemetry", {}).get("temp_f")
            if isinstance(entity, str) and entity.startswith("sensor."):
                return entity
    raise DeployError("config/site.yaml does not define an enabled temperature canary sensor")


def local_preflight(repo: Path = REPO, source: Path = SOURCE, *, require_clean: bool) -> Candidate:
    for path in sorted(source.rglob("*.yaml")):
        try:
            yaml.load(path.read_text(encoding="utf-8"), Loader=HAConfigLoader)
        except (OSError, yaml.YAMLError) as error:
            raise DeployError(f"local YAML syntax check failed for {path}: {error}") from error
    if subprocess.run([sys.executable, str(repo / "scripts/secret_scan.py"), str(source)], cwd=repo, check=False).returncode:
        raise DeployError("local secret scan rejected the deployable HA tree")
    with tempfile.TemporaryDirectory(prefix="sproutie-render-check-") as directory:
        rendered = Path(directory) / "20_device_roles.yaml"
        result = subprocess.run([
            sys.executable, str(repo / "scripts/render_r1_role_scripts.py"),
            "--site", str(repo / "config/site.yaml"), "--output", str(rendered),
        ], cwd=repo, check=False)
        if result.returncode or rendered.read_bytes() != (source / "scripts/20_device_roles.yaml").read_bytes():
            raise DeployError("generated HA role scripts are stale; render and commit them first")
    if require_clean and not git_is_clean(repo):
        raise DeployError("real deployments require a completely clean Git worktree so the recorded commit identifies every byte")
    files = local_manifest(source)
    return Candidate(git_commit(repo), files, build_archive(source, files), load_canary_entity(repo / "config/site.yaml"))


class SSHTransportProtocol:
    def inventory(self, base: str) -> dict[str, str]: ...
    def read_json(self, path: str) -> dict[str, Any] | None: ...
    def create_stage(self, stage_path: str, archive: bytes) -> None: ...
    def write_stage_json(self, stage_path: str, name: str, payload: Mapping[str, Any]) -> None: ...
    def validate_stage(self, stage_path: str) -> None: ...
    def apply_stage(self, stage_path: str, rollback_path: str) -> None: ...
    def write_json(self, path: str, payload: Mapping[str, Any]) -> None: ...
    def cleanup_stage(self, stage_path: str) -> None: ...
    def copy_backup_to_stage(self, backup_path: str, stage_path: str) -> None: ...


class SSHTransport(SSHTransportProtocol):
    """Strict-host-key SSH transport. No HA credential is passed to it."""

    def __init__(self, host: str, user: str, identity: Path, known_hosts: Path):
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", host) or not re.fullmatch(r"[A-Za-z0-9._-]+", user):
            raise DeployError("unsafe SSH host or user")
        self.prefix = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o",
            f"UserKnownHostsFile={known_hosts}", "-o", "StrictHostKeyChecking=yes", "-o",
            "IdentitiesOnly=yes", "-i", str(identity), f"{user}@{host}"]

    def _run(self, command: str, *, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment.pop("HA_ACCESS_TOKEN", None)
        return subprocess.run(
            self.prefix + [command],
            input=input_bytes,
            capture_output=True,
            check=check,
            env=environment,
        )

    @staticmethod
    def _safe_remote_base(base: str) -> None:
        path = PurePosixPath(base)
        allowed_parent = str(path.parent) in {f"{STATE_ROOT}/stages", f"{STATE_ROOT}/rollbacks"}
        allowed = base == REMOTE_CONFIG or (allowed_parent and SAFE_ID.fullmatch(path.name))
        if not allowed or ".." in path.parts:
            raise DeployError(f"unsafe remote base: {base}")

    def inventory(self, base: str) -> dict[str, str]:
        self._safe_remote_base(base)
        roots = " ".join(shlex.quote(root) for root in MANAGED_ROOTS)
        command = (f"set -eu; base={shlex.quote(base)}; for root in {roots}; do target=\"$base/$root\"; "
            "if [ -L \"$target\" ]; then printf 'SYMLINK\\t%s\\n' \"$target\"; "
            "elif [ -f \"$target\" ]; then sudo -n sha256sum \"$target\"; "
            "elif [ -d \"$target\" ]; then sudo -n find \"$target\" -type l -print | sed 's/^/SYMLINK\\t/'; "
            "sudo -n find \"$target\" -type f -exec sha256sum {} \\;; fi; done")
        result = self._run(command)
        files: dict[str, str] = {}
        prefix = base.rstrip("/") + "/"
        for line in result.stdout.decode("utf-8").splitlines():
            if line.startswith("SYMLINK\t"):
                raise DriftError(f"remote managed tree contains a symlink: {line.split(chr(9), 1)[1]}")
            match = HASH_LINE.fullmatch(line)
            if not match:
                raise DeployError(f"unexpected remote inventory output: {line!r}")
            absolute = match.group(2)
            if not absolute.startswith(prefix):
                raise DeployError(f"remote inventory escaped its base: {absolute}")
            relative = absolute[len(prefix):]
            validate_relative_path(relative)
            files[relative] = match.group(1)
        return dict(sorted(files.items()))

    def read_json(self, path: str) -> dict[str, Any] | None:
        parsed = PurePosixPath(path)
        rollback_parent = parsed.parent
        valid_rollback_ledger = (
            parsed.name == "deployed.json"
            and str(rollback_parent.parent) == f"{STATE_ROOT}/rollbacks"
            and SAFE_ID.fullmatch(rollback_parent.name)
        )
        if path != LEDGER_PATH and not valid_rollback_ledger:
            raise DeployError(f"unsafe remote JSON path: {path}")
        quoted = shlex.quote(path)
        result = self._run(f"if sudo -n test -f {quoted}; then sudo -n cat {quoted}; fi")
        if not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise DeployError(f"invalid remote JSON ledger at {path}") from error
        if not isinstance(payload, dict):
            raise DeployError(f"remote JSON ledger is not an object: {path}")
        return payload

    def _atomic_json_command(self, path: str) -> str:
        parent = str(PurePosixPath(path).parent)
        temporary = f"{path}.tmp"
        inner = f"umask 077; cat > {temporary}; mv {temporary} {path}"
        return f"sudo -n mkdir -p {shlex.quote(parent)} && sudo -n chmod 700 {shlex.quote(parent)} && sudo -n sh -c {shlex.quote(inner)}"

    def write_json(self, path: str, payload: Mapping[str, Any]) -> None:
        if path != LEDGER_PATH:
            raise DeployError(f"unsafe deployed-ledger write: {path}")
        self._run(self._atomic_json_command(path), input_bytes=(json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())

    def write_stage_json(self, stage_path: str, name: str, payload: Mapping[str, Any]) -> None:
        self._safe_remote_base(stage_path)
        if not re.fullmatch(r"\.[a-z0-9-]+\.json", name):
            raise DeployError("unsafe stage metadata name")
        self._run(self._atomic_json_command(f"{stage_path}/{name}"), input_bytes=(json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())

    def create_stage(self, stage_path: str, archive: bytes) -> None:
        self._safe_remote_base(stage_path)
        quoted = shlex.quote(stage_path)
        command = (f"sudo -n mkdir -p {shlex.quote(STATE_ROOT + '/stages')} && sudo -n chmod 700 {shlex.quote(STATE_ROOT)} {shlex.quote(STATE_ROOT + '/stages')} && sudo -n test ! -e {quoted} && "
            f"sudo -n mkdir {quoted} && sudo -n chmod 700 {quoted} && sudo -n tar -C {quoted} -xf - && "
            f"if sudo -n test -f {REMOTE_CONFIG}/secrets.yaml; then sudo -n ln -s {REMOTE_CONFIG}/secrets.yaml {quoted}/secrets.yaml; fi")
        self._run(command, input_bytes=archive)

    def _core_container(self) -> str:
        result = self._run("sudo -n docker ps --format '{{.Names}} {{.Image}}'")
        for line in result.stdout.decode().splitlines():
            name, _, image = line.partition(" ")
            if "home-assistant" in image and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                return name
        raise DeployError("Home Assistant Core container was not found; validation cannot proceed")

    def validate_stage(self, stage_path: str) -> None:
        self._safe_remote_base(stage_path)
        check = (
            f"docker exec {shlex.quote(self._core_container())} python -m homeassistant "
            f"--config {shlex.quote(stage_path)} --script check_config"
        )
        inner = (
            "umask 077; report=$(mktemp /tmp/sproutie-ha-check.XXXXXX); "
            "trap 'rm -f \"$report\"' EXIT INT TERM; status=0; "
            f"{check} >\"$report\" 2>&1 || status=$?; "
            "if grep -q 'ERROR:' \"$report\"; then status=1; fi; exit \"$status\""
        )
        command = f"sudo -n sh -c {shlex.quote(inner)}"
        result = self._run(command, check=False)
        if result.returncode != 0:
            raise CoreValidationError("Home Assistant Core rejected the staged configuration")

    def apply_stage(self, stage_path: str, rollback_path: str) -> None:
        self._safe_remote_base(stage_path)
        self._safe_remote_base(rollback_path)
        roots = " ".join(shlex.quote(root) for root in MANAGED_ROOTS)
        previous = shlex.quote(f"{stage_path}/.previous-ledger.json")
        pending = shlex.quote(f"{stage_path}/.pending-ledger.json")
        command = (f"set -eu; stage={shlex.quote(stage_path)}; rollback={shlex.quote(rollback_path)}; "
            f"sudo -n test -f {previous}; sudo -n test -f {pending}; sudo -n test ! -e \"$rollback\"; "
            "sudo -n mkdir -p \"$rollback\"; sudo -n chmod 700 \"$rollback\"; "
            f"for root in {roots}; do if sudo -n test -e {REMOTE_CONFIG}/\"$root\"; then sudo -n cp -a {REMOTE_CONFIG}/\"$root\" \"$rollback/$root\"; fi; done; "
            f"sudo -n cp {previous} \"$rollback/deployed.json\"; "
            "rollback_active() { code=$?; trap - EXIT INT TERM; "
            f"for root in {roots}; do sudo -n rm -rf {REMOTE_CONFIG}/\"$root\"; if sudo -n test -e \"$rollback/$root\"; then sudo -n cp -a \"$rollback/$root\" {REMOTE_CONFIG}/\"$root\"; fi; done; "
            f"sudo -n cp \"$rollback/deployed.json\" {shlex.quote(LEDGER_PATH + '.tmp')}; sudo -n mv {shlex.quote(LEDGER_PATH + '.tmp')} {shlex.quote(LEDGER_PATH)}; exit \"$code\"; }}; "
            "trap rollback_active EXIT INT TERM; "
            f"for root in {roots}; do sudo -n rm -rf {REMOTE_CONFIG}/\"$root\"; if sudo -n test -e \"$stage/$root\"; then sudo -n cp -a \"$stage/$root\" {REMOTE_CONFIG}/\"$root\"; fi; done; "
            f"sudo -n mkdir -p {shlex.quote(STATE_ROOT)}; sudo -n chmod 700 {shlex.quote(STATE_ROOT)}; "
            f"sudo -n cp {pending} {shlex.quote(LEDGER_PATH + '.tmp')}; sudo -n chmod 600 {shlex.quote(LEDGER_PATH + '.tmp')}; sudo -n mv {shlex.quote(LEDGER_PATH + '.tmp')} {shlex.quote(LEDGER_PATH)}; trap - EXIT INT TERM")
        self._run(command)

    def cleanup_stage(self, stage_path: str) -> None:
        self._safe_remote_base(stage_path)
        self._run(f"sudo -n rm -rf {shlex.quote(stage_path)}")

    def copy_backup_to_stage(self, backup_path: str, stage_path: str) -> None:
        self._safe_remote_base(backup_path)
        self._safe_remote_base(stage_path)
        roots = " ".join(shlex.quote(root) for root in MANAGED_ROOTS)
        command = (f"sudo -n test -d {shlex.quote(backup_path)}; sudo -n test ! -e {shlex.quote(stage_path)}; sudo -n mkdir -p {shlex.quote(stage_path)}; sudo -n chmod 700 {shlex.quote(stage_path)}; "
            f"for root in {roots}; do if sudo -n test -e {shlex.quote(backup_path)}/\"$root\"; then sudo -n cp -a {shlex.quote(backup_path)}/\"$root\" {shlex.quote(stage_path)}/\"$root\"; fi; done; "
            f"if sudo -n test -f {REMOTE_CONFIG}/secrets.yaml; then sudo -n ln -s {REMOTE_CONFIG}/secrets.yaml {shlex.quote(stage_path)}/secrets.yaml; fi")
        self._run(command)


class HAClient:
    """Local REST client. The bearer token never enters SSH, argv, or a file."""
    def __init__(self, base_url: str, token: str, *, timeout: float = 15, sleep: Callable[[float], None] = time.sleep):
        if not base_url.startswith(("http://", "https://")):
            raise DeployError("HA_URL must be http:// or https://")
        self.base_url, self.token, self.timeout, self.sleep = base_url.rstrip("/"), token, timeout, sleep

    def request(self, path: str, *, method: str = "GET", data: bytes | None = None) -> Any:
        request = Request(f"{self.base_url}{path}", method=method, data=data, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/json", "Content-Type": "application/json"})
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310 -- operator-supplied HA URL
            body = response.read()
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise DeployError(f"Home Assistant returned invalid JSON for {path}") from error

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise DeployError(f"canary sensor returned an invalid last_updated marker: {value!r}") from error
        if parsed.tzinfo is None:
            raise DeployError(f"canary sensor returned a timezone-free last_updated marker: {value!r}")
        return parsed

    def state(self, entity: str) -> dict[str, Any]:
        try:
            payload = self.request(f"/api/states/{entity}")
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise DeployError(f"cannot read canary sensor {entity}: {error}") from error
        if not isinstance(payload, dict) or str(payload.get("state", "")).lower() in UNAVAILABLE:
            raise DeployError(f"canary sensor is unavailable: {entity}")
        try:
            if not math.isfinite(float(payload["state"])):
                raise ValueError
        except (KeyError, TypeError, ValueError) as error:
            raise DeployError(f"canary sensor is not reporting a finite numeric value: {entity}") from error
        if not isinstance(payload.get("last_updated"), str):
            raise DeployError(f"canary sensor has no last_updated marker: {entity}")
        return payload

    def activate(self, activation: Activation, *, ready_timeout: float) -> None:
        if activation.kind == "none": return
        domain, service = activation.services[0]
        try:
            self.request(f"/api/services/{domain}/{service}", method="POST", data=b"{}")
        except HTTPError as error:
            raise DeployError(f"{domain}.{service} was rejected with HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise DeployError(f"{domain}.{service} outcome is unverified after a connection failure: {error}") from error
        if activation.kind == "restart": self.wait_ready(ready_timeout)

    def wait_ready(self, timeout: float) -> None:
        deadline, last_error = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            try:
                if isinstance(self.request("/api/"), dict): return
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                last_error = error
            self.sleep(min(5, max(0, deadline - time.monotonic())))
        raise DeployError(f"Home Assistant did not become ready after restart: {last_error}")

    def verify_canary(self, entity: str, before: Mapping[str, Any], timeout: float, *, require_update: bool = True) -> None:
        previous, deadline, last_error = before.get("last_updated"), time.monotonic() + timeout, None
        previous_time = self._timestamp(previous)
        while time.monotonic() < deadline:
            try:
                current = self.state(entity)
                current_time = self._timestamp(current.get("last_updated"))
                if not require_update or current_time > previous_time:
                    print(f"Canary passed: {entity} last_updated={current.get('last_updated')}")
                    return
            except DeployError as error:
                last_error = error
            self.sleep(min(5, max(0, deadline - time.monotonic())))
        detail = f": {last_error}" if last_error else ""
        raise DeployError(f"canary sensor did not publish a newer update within {timeout:g}s{detail}")


def verify_devices(repo: Path, ha_url: str, token: str) -> None:
    environment = os.environ.copy()
    environment.update({"HA_URL": ha_url, "HA_ACCESS_TOKEN": token})
    result = subprocess.run([sys.executable, str(repo / "scripts/verify_devices.py"), "--site", str(repo / "config/site.yaml")], cwd=repo, env=environment, check=False)
    if result.returncode:
        raise DeployError(f"device verification failed with exit code {result.returncode}")


def ledger_payload(candidate: Candidate, *, deployment_id: str, status: str, activation: Activation, rollback_id: str | None) -> dict[str, Any]:
    return {"schema": SCHEMA, "deployment_id": deployment_id, "commit": candidate.commit, "files": candidate.files,
        "status": status, "activation": {"kind": activation.kind, "reason": activation.reason},
        "rollback_id": rollback_id, "updated_at": utc_now()}


def baseline_payload(inspection: Inspection) -> dict[str, Any]:
    return inspection.ledger or {
        "schema": SCHEMA,
        "deployment_id": None,
        "commit": inspection.bootstrap_commit,
        "files": inspection.current,
        "status": "declared-bootstrap" if inspection.bootstrap_commit else "untracked-baseline",
        "activation": None,
        "rollback_id": None,
        "updated_at": utc_now(),
    }


def safe_run_id(prefix: str, commit: str) -> str:
    value = f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%Sz').lower()}-{commit[:12]}"
    if not SAFE_ID.fullmatch(value): raise DeployError("generated deployment identifier is unsafe")
    return value


def confirm_exact(action: str, identifier: str, input_fn: Callable[[str], str] = input) -> None:
    if not sys.stdin.isatty(): raise DeployError("live mutation requires an interactive terminal; unattended deploys are forbidden")
    expected = f"{action} {identifier}"
    if input_fn(f"Type {expected!r} to continue: ") != expected:
        raise DeployError("confirmation did not match; nothing was changed")


def is_verified_noop(candidate: Candidate, inspection: Inspection) -> bool:
    return (
        not inspection.desired_changes
        and inspection.ledger is not None
        and inspection.ledger.get("commit") == candidate.commit
        and inspection.ledger.get("status") == "verified"
    )


def activation_label(activation: Activation) -> str:
    if not activation.services:
        return "no-reload"
    domain, service = activation.services[0]
    return f"{domain}.{service}"


def deploy_candidate(candidate: Candidate, inspection: Inspection, transport: SSHTransportProtocol, ha: HAClient, *,
    repo: Path, ha_url: str, token: str, canary_timeout: float, ready_timeout: float,
    verifier: Callable[[Path, str, str], None] = verify_devices) -> str:
    assert_inspection_safe(inspection)
    if is_verified_noop(candidate, inspection):
        print(f"No-op: {candidate.commit} is already deployed and verified.")
        return "noop"
    confirm_exact("deploy", f"{candidate.commit} via {activation_label(inspection.activation)}")
    deployment_id = safe_run_id("dep", candidate.commit)
    rollback_id = safe_run_id("rb", candidate.commit) if inspection.desired_changes else None
    before = ha.state(candidate.canary_entity)
    if not inspection.desired_changes:
        if transport.inventory(REMOTE_CONFIG) != inspection.current or transport.read_json(LEDGER_PATH) != inspection.ledger:
            raise DriftError("remote managed files or ledger changed after inspection; metadata bootstrap stopped")
        verifier(repo, ha_url, token)
        ha.verify_canary(candidate.canary_entity, before, canary_timeout)
        transport.write_json(LEDGER_PATH, ledger_payload(candidate, deployment_id=deployment_id, status="verified", activation=inspection.activation, rollback_id=None))
        print(f"Recorded verified metadata for {candidate.commit}; no managed file changed.")
        return deployment_id
    stage_path, rollback_path = f"{STATE_ROOT}/stages/{deployment_id}", f"{STATE_ROOT}/rollbacks/{rollback_id}"
    pending = ledger_payload(candidate, deployment_id=deployment_id, status="pending-verification", activation=inspection.activation, rollback_id=rollback_id)
    applied = False
    try:
        transport.create_stage(stage_path, candidate.archive)
        if validate_manifest(transport.inventory(stage_path)) != candidate.files:
            raise DeployError("staged hashes do not exactly match the local candidate")
        transport.validate_stage(stage_path)
        if validate_manifest(transport.inventory(stage_path)) != candidate.files:
            raise DeployError("Core validation changed the staged managed files")
        raw_ledger = transport.read_json(LEDGER_PATH)
        current_ledger = parse_ledger(raw_ledger) if raw_ledger is not None else None
        if validate_manifest(transport.inventory(REMOTE_CONFIG), allow_empty=True) != inspection.current or current_ledger != inspection.ledger:
            raise DriftError("remote files or ledger changed after validation; apply stopped")
        transport.write_stage_json(stage_path, ".previous-ledger.json", baseline_payload(inspection))
        transport.write_stage_json(stage_path, ".pending-ledger.json", pending)
        transport.apply_stage(stage_path, rollback_path)
        applied = True
        ha.activate(inspection.activation, ready_timeout=ready_timeout)
        ha.verify_canary(candidate.canary_entity, before, canary_timeout)
        verifier(repo, ha_url, token)
        if validate_manifest(transport.inventory(REMOTE_CONFIG)) != candidate.files:
            raise DriftError("active managed files changed before verification completed")
        verified = dict(pending); verified.update(status="verified", updated_at=utc_now())
        transport.write_json(LEDGER_PATH, verified)
    except Exception:
        if applied:
            print(f"Candidate applied but verification incomplete. With Jeff's exact approval: make rollback ROLLBACK_ID={rollback_id}", file=sys.stderr)
        raise
    finally:
        transport.cleanup_stage(stage_path)
    print(f"Deployment verified: commit={candidate.commit} rollback_id={rollback_id}")
    return deployment_id


def rollback_candidate(rollback_id: str, transport: SSHTransportProtocol, ha: HAClient, *, repo: Path, ha_url: str,
    token: str, canary_entity: str, canary_timeout: float, ready_timeout: float,
    verifier: Callable[[Path, str, str], None] = verify_devices) -> str:
    if not SAFE_ID.fullmatch(rollback_id): raise DeployError("rollback ID contains unsafe characters")
    current_raw = transport.read_json(LEDGER_PATH)
    if current_raw is None: raise DeployError("cannot rollback without a current ledger")
    current_ledger = parse_ledger(current_raw)
    current_files = validate_manifest(transport.inventory(REMOTE_CONFIG), allow_empty=True)
    if diff_files(current_ledger["files"], current_files): raise DriftError("remote drift blocks rollback")
    backup_path = f"{STATE_ROOT}/rollbacks/{rollback_id}"
    target_raw = transport.read_json(f"{backup_path}/deployed.json")
    if target_raw is None: raise DeployError(f"rollback snapshot does not exist: {rollback_id}")
    target = parse_ledger(target_raw)
    confirm_exact("rollback", f"{rollback_id} via homeassistant.restart")
    commit = target.get("commit") or "0" * 40
    operation_id, new_rollback_id = safe_run_id("rollback", commit), safe_run_id("rb", current_ledger.get("commit") or "0" * 40)
    stage_path, new_backup = f"{STATE_ROOT}/stages/{operation_id}", f"{STATE_ROOT}/rollbacks/{new_rollback_id}"
    activation = Activation("restart", (("homeassistant", "restart"),), "rollback always reloads the complete prior managed tree")
    candidate = Candidate(commit, target["files"], b"", canary_entity)
    pending = ledger_payload(candidate, deployment_id=operation_id, status="pending-verification", activation=activation, rollback_id=new_rollback_id)
    before = ha.state(canary_entity)
    applied = False
    try:
        transport.copy_backup_to_stage(backup_path, stage_path)
        if validate_manifest(transport.inventory(stage_path), allow_empty=True) != target["files"]: raise DriftError("rollback snapshot bytes do not match its manifest")
        transport.validate_stage(stage_path)
        if transport.inventory(REMOTE_CONFIG) != current_files or transport.read_json(LEDGER_PATH) != current_raw: raise DriftError("remote changed after rollback validation")
        transport.write_stage_json(stage_path, ".previous-ledger.json", current_ledger)
        transport.write_stage_json(stage_path, ".pending-ledger.json", pending)
        transport.apply_stage(stage_path, new_backup)
        applied = True
        ha.activate(activation, ready_timeout=ready_timeout)
        ha.verify_canary(canary_entity, before, canary_timeout)
        verifier(repo, ha_url, token)
        if validate_manifest(transport.inventory(REMOTE_CONFIG), allow_empty=True) != target["files"]: raise DriftError("active files do not match rollback target")
        verified = dict(pending); verified.update(status="verified", updated_at=utc_now())
        transport.write_json(LEDGER_PATH, verified)
    except Exception:
        if applied:
            print(
                f"Rollback target was applied but verification is incomplete. With Jeff's exact approval, "
                f"restore the pre-rollback tree with: make rollback ROLLBACK_ID={new_rollback_id}",
                file=sys.stderr,
            )
        raise
    finally:
        transport.cleanup_stage(stage_path)
    print(f"Rollback verified: source={rollback_id} new_recovery_point={new_rollback_id}")
    return operation_id


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--local-only", action="store_true")
    mode.add_argument("--rollback", metavar="ROLLBACK_ID")
    result.add_argument("--bootstrap-ref")
    result.add_argument("--host", default="192.168.1.232")
    result.add_argument("--user", default="kegsofduff")
    result.add_argument("--identity", type=Path, default=Path(os.environ.get("HA_SSH_IDENTITY", "~/.ssh/id_ed25519")).expanduser())
    result.add_argument("--known-hosts", type=Path, default=Path(os.environ.get("HA_SSH_KNOWN_HOSTS", "~/.ssh/known_hosts")).expanduser())
    result.add_argument("--canary-timeout", type=float, default=180)
    result.add_argument("--ready-timeout", type=float, default=180)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.local_only:
            if args.bootstrap_ref: raise DeployError("--bootstrap-ref requires a remote mode")
            candidate = local_preflight(require_clean=False)
            clean = "clean" if git_is_clean(REPO) else "dirty (real deploy would stop)"
            print(f"Local preflight passed: commit={candidate.commit} files={len(candidate.files)} worktree={clean}")
            return 0
        transport = SSHTransport(args.host, args.user, args.identity, args.known_hosts)
        if args.rollback:
            if args.bootstrap_ref: raise DeployError("--bootstrap-ref cannot be combined with rollback")
            ha_url, token = os.environ.get("HA_URL"), os.environ.get("HA_ACCESS_TOKEN")
            if not ha_url or not token: raise DeployError("rollback requires HA_URL and HA_ACCESS_TOKEN in the environment")
            rollback_candidate(args.rollback, transport, HAClient(ha_url, token), repo=REPO, ha_url=ha_url, token=token,
                canary_entity=load_canary_entity(), canary_timeout=args.canary_timeout, ready_timeout=args.ready_timeout)
            return 0
        candidate = local_preflight(require_clean=not args.dry_run)
        if args.dry_run and not git_is_clean(REPO):
            print(f"Candidate provenance: dirty worktree at HEAD {candidate.commit}; a real deploy would stop.")
        bootstrap_commit = resolve_git_commit(args.bootstrap_ref) if args.bootstrap_ref else None
        bootstrap_files = manifest_from_git(bootstrap_commit) if bootstrap_commit else None
        inspection = inspect_remote(candidate, transport, bootstrap_files, bootstrap_commit)
        print_inspection(inspection)
        if args.dry_run:
            assert_inspection_safe(inspection)
            print("Dry run complete: no remote file, ledger, service, or device was changed.")
            return 0
        assert_inspection_safe(inspection)
        if is_verified_noop(candidate, inspection):
            print(f"No-op: {candidate.commit} is already deployed and verified.")
            return 0
        ha_url, token = os.environ.get("HA_URL"), os.environ.get("HA_ACCESS_TOKEN")
        if not ha_url or not token: raise DeployError("deploy requires HA_URL and HA_ACCESS_TOKEN in the environment")
        deploy_candidate(candidate, inspection, transport, HAClient(ha_url, token), repo=REPO, ha_url=ha_url, token=token,
            canary_timeout=args.canary_timeout, ready_timeout=args.ready_timeout)
        return 0
    except (DeployError, OSError, subprocess.CalledProcessError) as error:
        print(f"DEPLOY STOPPED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
