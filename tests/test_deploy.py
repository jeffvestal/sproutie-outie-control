import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validated_deploy", REPO / "scripts" / "deploy.py")
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = deploy
SPEC.loader.exec_module(deploy)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def manifest(version):
    return {
        "configuration.yaml": digest(f"config-{version}"),
        "automations.yaml": digest(f"automations-{version}"),
        "scenes.yaml": digest(f"scenes-{version}"),
        "template.yaml": digest(f"template-{version}"),
        "scripts/main.yaml": digest(f"scripts-{version}"),
        "helpers/main.yaml": digest(f"helpers-{version}"),
        "dashboards/r1.yaml": digest(f"dashboard-{version}"),
        "themes/.gitkeep": digest(f"theme-{version}"),
    }


def ledger(files, commit="a" * 40, status="verified"):
    return {
        "schema": 1,
        "deployment_id": "dep-old",
        "commit": commit,
        "files": copy.deepcopy(files),
        "status": status,
        "activation": {"kind": "restart", "reason": "test"},
        "rollback_id": "rb-old",
        "updated_at": "2026-09-01T00:00:00Z",
    }


class FakeTransport:
    def __init__(self, current, current_ledger=None):
        self.current = copy.deepcopy(current)
        self.ledger = copy.deepcopy(current_ledger)
        self.stages = {}
        self.stage_metadata = {}
        self.backups = {}
        self.events = []
        self.validation_error = None
        self.mutate_after_validation = None

    def inventory(self, base):
        self.events.append(("inventory", base))
        if base == deploy.REMOTE_CONFIG:
            return copy.deepcopy(self.current)
        return copy.deepcopy(self.stages.get(base, self.backups.get(base, {}).get("files", {})))

    def read_json(self, path):
        self.events.append(("read_json", path))
        if path == deploy.LEDGER_PATH:
            return copy.deepcopy(self.ledger)
        suffix = "/deployed.json"
        if path.endswith(suffix):
            return copy.deepcopy(self.backups.get(path[: -len(suffix)], {}).get("ledger"))
        return None

    def create_stage(self, stage_path, _archive):
        self.events.append(("create_stage", stage_path))
        self.stages[stage_path] = copy.deepcopy(self.candidate_files)

    def write_stage_json(self, stage_path, name, payload):
        self.events.append(("write_stage_json", name))
        self.stage_metadata[(stage_path, name)] = copy.deepcopy(payload)

    def validate_stage(self, stage_path):
        self.events.append(("validate_stage", stage_path))
        if self.validation_error:
            raise self.validation_error
        if self.mutate_after_validation:
            self.stages[stage_path].update(self.mutate_after_validation)

    def apply_stage(self, stage_path, rollback_path):
        self.events.append(("apply_stage", rollback_path))
        previous = self.stage_metadata[(stage_path, ".previous-ledger.json")]
        pending = self.stage_metadata[(stage_path, ".pending-ledger.json")]
        self.backups[rollback_path] = {"files": copy.deepcopy(self.current), "ledger": copy.deepcopy(previous)}
        self.current = copy.deepcopy(self.stages[stage_path])
        self.ledger = copy.deepcopy(pending)

    def write_json(self, path, payload):
        self.events.append(("write_json", path, payload["status"]))
        self.ledger = copy.deepcopy(payload)

    def cleanup_stage(self, stage_path):
        self.events.append(("cleanup_stage", stage_path))
        self.stages.pop(stage_path, None)

    def copy_backup_to_stage(self, backup_path, stage_path):
        self.events.append(("copy_backup_to_stage", backup_path))
        self.stages[stage_path] = copy.deepcopy(self.backups[backup_path]["files"])


class FakeHA:
    def __init__(self):
        self.events = []
        self.fail_canary = False

    def state(self, entity):
        self.events.append(("state", entity))
        return {"state": "72.1", "last_updated": "2026-09-01T00:00:00Z"}

    def activate(self, activation, *, ready_timeout):
        self.events.append(("activate", activation.kind, ready_timeout))

    def verify_canary(self, entity, before, timeout, *, require_update=True):
        self.events.append(("canary", entity, timeout, require_update))
        if self.fail_canary:
            raise deploy.DeployError("simulated stale canary")


class DeployTests(unittest.TestCase):
    def candidate(self, files=None, commit="b" * 40):
        return deploy.Candidate(commit, copy.deepcopy(files or manifest("new")), b"archive", "sensor.monitor2_temperature")

    def inspection(self, candidate, transport, bootstrap=None):
        transport.candidate_files = copy.deepcopy(candidate.files)
        return deploy.inspect_remote(candidate, transport, bootstrap)

    def run_candidate(self, candidate, inspection, transport, ha, verifier=lambda *_: None):
        with mock.patch.object(deploy, "confirm_exact"):
            return deploy.deploy_candidate(
                candidate, inspection, transport, ha, repo=REPO, ha_url="http://ha.test",
                token="test-token", canary_timeout=1, ready_timeout=1, verifier=verifier,
            )

    def test_archive_contains_only_manifest_members_and_never_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            for root in deploy.MANAGED_ROOTS:
                path = source / root
                if Path(root).suffix:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(root)
                else:
                    path.mkdir(parents=True)
                    (path / "main.yaml").write_text(root)
            (source / "secrets.yaml").write_text("password: no")
            (source / "docs").mkdir()
            (source / "docs/readme.md").write_text("not deployed")
            files = deploy.local_manifest(source)
            archive = deploy.build_archive(source, files)
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
                names = {member.name for member in tar.getmembers() if member.isfile()}
            self.assertEqual(names, set(files))
            self.assertNotIn("secrets.yaml", names)
            self.assertFalse(any(name.startswith("docs/") for name in names))

    def test_manifest_rejects_secret_and_parent_paths(self):
        with self.assertRaises(deploy.DeployError):
            deploy.validate_manifest({"secrets.yaml": "0" * 64})
        with self.assertRaises(deploy.DeployError):
            deploy.validate_manifest({"scripts/../secrets.yaml": "0" * 64})

    def test_exact_diff_and_activation_selection(self):
        changes = deploy.diff_files(
            {"scripts/old.yaml": digest("old"), "scenes.yaml": digest("same")},
            {"scripts/new.yaml": digest("new"), "scenes.yaml": digest("same")},
        )
        self.assertEqual([(item.status, item.path) for item in changes], [("A", "scripts/new.yaml"), ("D", "scripts/old.yaml")])
        self.assertEqual(deploy.activation_for(changes).services, (("script", "reload"),))
        multi = deploy.activation_for(changes + (deploy.FileChange("M", "automations.yaml"),))
        self.assertEqual(multi.kind, "restart")
        self.assertEqual(deploy.activation_for((deploy.FileChange("M", "dashboards/r1.yaml"),)).kind, "none")

    def test_remote_drift_blocks_even_when_candidate_would_replace_it(self):
        old, changed = manifest("old"), manifest("old")
        changed["automations.yaml"] = digest("hand edit")
        transport = FakeTransport(changed, ledger(old))
        candidate = self.candidate()
        inspection = self.inspection(candidate, transport)
        self.assertTrue(inspection.remote_drift)
        with self.assertRaises(deploy.DriftError):
            deploy.assert_inspection_safe(inspection)
        self.assertFalse(any(event[0] in {"create_stage", "apply_stage", "write_json"} for event in transport.events))

    def test_dry_run_cli_uses_only_remote_reads(self):
        files = manifest("same")
        candidate = self.candidate(files=files)
        transport = FakeTransport(files, ledger(files, commit=candidate.commit))
        with mock.patch.object(deploy, "local_preflight", return_value=candidate), \
             mock.patch.object(deploy, "git_is_clean", return_value=True), \
             mock.patch.object(deploy, "SSHTransport", return_value=transport):
            self.assertEqual(deploy.main(["--dry-run"]), 0)
        self.assertFalse(any(event[0] in {"create_stage", "apply_stage", "write_json", "write_stage_json"} for event in transport.events))

    def test_unrecognized_ledger_shape_fails_closed(self):
        payload = ledger(manifest("same"))
        payload["unexpected"] = "do not trust this"
        with self.assertRaisesRegex(deploy.DeployError, "unexpected fields"):
            deploy.parse_ledger(payload)

    def test_missing_ledger_requires_matching_candidate_or_bootstrap_ref(self):
        old = manifest("old")
        transport = FakeTransport(old)
        candidate = self.candidate()
        blocked = self.inspection(candidate, transport)
        self.assertIsNotNone(blocked.baseline_error)
        allowed = self.inspection(candidate, transport, bootstrap=old)
        deploy.assert_inspection_safe(allowed)

    def test_declared_bootstrap_commit_is_preserved_for_first_rollback(self):
        old = manifest("old")
        transport = FakeTransport(old)
        candidate = self.candidate()
        inspection = deploy.inspect_remote(candidate, transport, old, "a" * 40)
        baseline = deploy.baseline_payload(inspection)
        self.assertEqual(baseline["commit"], "a" * 40)
        self.assertEqual(baseline["status"], "declared-bootstrap")

    def test_core_validation_failure_never_applies_or_reloads(self):
        old = manifest("old")
        transport = FakeTransport(old, ledger(old))
        transport.validation_error = deploy.CoreValidationError("broken YAML")
        candidate = self.candidate()
        inspection = self.inspection(candidate, transport)
        ha = FakeHA()
        with self.assertRaises(deploy.CoreValidationError):
            self.run_candidate(candidate, inspection, transport, ha)
        self.assertEqual(transport.current, old)
        self.assertEqual(transport.ledger["status"], "verified")
        self.assertFalse(any(event[0] == "apply_stage" for event in transport.events))
        self.assertFalse(any(event[0] == "activate" for event in ha.events))

    def test_core_validation_may_not_change_staged_bytes(self):
        old = manifest("old")
        transport = FakeTransport(old, ledger(old))
        transport.mutate_after_validation = {"automations.yaml": digest("validator mutation")}
        candidate = self.candidate()
        inspection = self.inspection(candidate, transport)
        with self.assertRaisesRegex(deploy.DeployError, "Core validation changed"):
            self.run_candidate(candidate, inspection, transport, FakeHA())
        self.assertFalse(any(event[0] == "apply_stage" for event in transport.events))

    def test_toctou_remote_change_after_validation_stops_apply(self):
        old = manifest("old")
        transport = FakeTransport(old, ledger(old))
        candidate = self.candidate()
        inspection = self.inspection(candidate, transport)
        original_validate = transport.validate_stage

        def validate_and_drift(stage_path):
            original_validate(stage_path)
            transport.current["automations.yaml"] = digest("late hand edit")

        transport.validate_stage = validate_and_drift
        with self.assertRaises(deploy.DriftError):
            self.run_candidate(candidate, inspection, transport, FakeHA())
        self.assertFalse(any(event[0] == "apply_stage" for event in transport.events))

    def test_success_records_verified_commit_and_recovery_snapshot(self):
        old = manifest("old")
        transport = FakeTransport(old, ledger(old))
        candidate = self.candidate()
        inspection = self.inspection(candidate, transport)
        ha = FakeHA()
        result = self.run_candidate(candidate, inspection, transport, ha)
        self.assertTrue(result.startswith("dep-"))
        self.assertEqual(transport.current, candidate.files)
        self.assertEqual(transport.ledger["commit"], candidate.commit)
        self.assertEqual(transport.ledger["status"], "verified")
        self.assertTrue(transport.backups)
        self.assertTrue(any(event[0] == "activate" for event in ha.events))
        self.assertTrue(any(event[0] == "canary" for event in ha.events))

    def test_canary_failure_leaves_pending_ledger_and_prints_explicit_rollback(self):
        old = manifest("old")
        transport = FakeTransport(old, ledger(old))
        candidate = self.candidate()
        inspection = self.inspection(candidate, transport)
        ha = FakeHA(); ha.fail_canary = True
        with self.assertRaisesRegex(deploy.DeployError, "stale canary"):
            self.run_candidate(candidate, inspection, transport, ha)
        self.assertEqual(transport.ledger["status"], "pending-verification")
        self.assertTrue(transport.ledger["rollback_id"].startswith("rb-"))

    def test_same_verified_commit_is_clean_noop(self):
        files = manifest("same")
        candidate = self.candidate(files=files)
        transport = FakeTransport(files, ledger(files, commit=candidate.commit))
        inspection = self.inspection(candidate, transport)
        result = self.run_candidate(candidate, inspection, transport, FakeHA())
        self.assertEqual(result, "noop")
        self.assertFalse(any(event[0] in {"create_stage", "apply_stage", "write_json"} for event in transport.events))

    def test_noop_cli_does_not_require_ha_token_or_construct_api_client(self):
        files = manifest("same")
        candidate = self.candidate(files=files)
        transport = FakeTransport(files, ledger(files, commit=candidate.commit))
        with mock.patch.object(deploy, "local_preflight", return_value=candidate), \
             mock.patch.object(deploy, "SSHTransport", return_value=transport), \
             mock.patch.object(deploy, "HAClient") as client, \
             mock.patch.dict(deploy.os.environ, {}, clear=True):
            self.assertEqual(deploy.main([]), 0)
        client.assert_not_called()

    def test_simulated_rollback_validates_then_restores_snapshot(self):
        old, current = manifest("old"), manifest("current")
        current_ledger = ledger(current, commit="c" * 40)
        transport = FakeTransport(current, current_ledger)
        rollback_id = "rb-approved-test"
        backup_path = f"{deploy.STATE_ROOT}/rollbacks/{rollback_id}"
        transport.backups[backup_path] = {"files": old, "ledger": ledger(old, commit="a" * 40)}
        ha = FakeHA()
        with mock.patch.object(deploy, "confirm_exact"):
            deploy.rollback_candidate(
                rollback_id, transport, ha, repo=REPO, ha_url="http://ha.test", token="test-token",
                canary_entity="sensor.monitor2_temperature", canary_timeout=1, ready_timeout=1,
                verifier=lambda *_: None,
            )
        self.assertEqual(transport.current, old)
        self.assertEqual(transport.ledger["status"], "verified")
        self.assertEqual(transport.ledger["commit"], "a" * 40)
        self.assertIn(("activate", "restart", 1), ha.events)

    def test_restart_http_rejection_is_not_treated_as_disconnect(self):
        client = deploy.HAClient("http://ha.test", "token", sleep=lambda _seconds: None)
        error = HTTPError("http://ha.test", 403, "forbidden", {}, None)
        with mock.patch.object(client, "request", side_effect=error):
            with self.assertRaisesRegex(deploy.DeployError, "HTTP 403"):
                client.activate(deploy.Activation("restart", (("homeassistant", "restart"),), "test"), ready_timeout=1)

    def test_canary_requires_a_numeric_sensor(self):
        client = deploy.HAClient("http://ha.test", "token")
        with mock.patch.object(client, "request", return_value={"state": "warm", "last_updated": "2026-09-01T00:00:00Z"}):
            with self.assertRaisesRegex(deploy.DeployError, "finite numeric"):
                client.state("sensor.monitor2_temperature")

    def test_unattended_confirmation_is_rejected(self):
        with mock.patch.object(deploy.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(deploy.DeployError, "unattended deploys are forbidden"):
                deploy.confirm_exact("deploy", "a" * 40)

    def test_remote_cleanup_targets_require_one_safe_generated_id(self):
        for path in (
            f"{deploy.STATE_ROOT}/stages/../escape",
            f"{deploy.STATE_ROOT}/stages/two/levels",
            f"{deploy.STATE_ROOT}/rollbacks/*",
        ):
            with self.subTest(path=path):
                with self.assertRaises(deploy.DeployError):
                    deploy.SSHTransport._safe_remote_base(path)

    def test_remote_apply_transaction_is_valid_posix_shell(self):
        transport = deploy.SSHTransport.__new__(deploy.SSHTransport)
        commands = []
        transport._run = lambda command, **_kwargs: commands.append(command)
        transport.apply_stage(
            f"{deploy.STATE_ROOT}/stages/dep-safe",
            f"{deploy.STATE_ROOT}/rollbacks/rb-safe",
        )
        self.assertEqual(len(commands), 1)
        result = subprocess.run(["sh", "-n", "-c", commands[0]], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rollback_active", commands[0])
        self.assertIn(f"{deploy.LEDGER_PATH}.tmp", commands[0])

    def test_core_check_command_hides_remote_report_and_is_valid_shell(self):
        transport = deploy.SSHTransport.__new__(deploy.SSHTransport)
        commands = []
        transport._core_container = lambda: "homeassistant"

        def capture(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess([], 0, b"", b"")

        transport._run = capture
        transport.validate_stage(f"{deploy.STATE_ROOT}/stages/dep-safe")
        self.assertEqual(len(commands), 1)
        result = subprocess.run(["sh", "-n", "-c", commands[0]], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('>"$report" 2>&1', commands[0])
        self.assertIn("ERROR:", commands[0])

    def test_verify_devices_keeps_token_out_of_argv(self):
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.object(deploy.subprocess, "run", return_value=completed) as run:
            deploy.verify_devices(REPO, "http://ha.test", "super-secret-token")
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("super-secret-token", command)
        self.assertEqual(environment["HA_ACCESS_TOKEN"], "super-secret-token")

    def test_ssh_process_cannot_inherit_ha_token(self):
        transport = deploy.SSHTransport("ha.test", "operator", Path("/tmp/key"), Path("/tmp/known-hosts"))
        completed = subprocess.CompletedProcess([], 0, b"", b"")
        with mock.patch.dict(deploy.os.environ, {"HA_ACCESS_TOKEN": "must-not-reach-ssh"}), \
             mock.patch.object(deploy.subprocess, "run", return_value=completed) as run:
            transport._run("true")
        self.assertNotIn("HA_ACCESS_TOKEN", run.call_args.kwargs["env"])
        self.assertNotIn("must-not-reach-ssh", run.call_args.args[0])

    def test_retired_prototype_cannot_activate(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts/deploy_r1_config.py"), "--activate"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("retired", result.stderr)


if __name__ == "__main__":
    unittest.main()
