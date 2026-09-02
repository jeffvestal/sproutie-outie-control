# Issue #9 — validated, supervised Home Assistant deploys

`scripts/deploy.sh` is the only supported writer for the committed `ha/` tree. `make deploy`
wraps it. The old `scripts/deploy_r1_config.py --activate` path is retired because it had no
remote-drift baseline or real dry-run diff. `upload.sftp` remains only until issue #10 retires the
v1 artifacts; do not use it for R1.

## Safety contract

- A real deploy or rollback requires a terminal and an exact typed confirmation. There is no
  noninteractive or force option.
- Real deploys require a completely clean Git worktree. `/config/.sproutie-deploy/deployed.json`
  records the exact 40-character commit, managed file hashes, activation reason, verification
  state, and recovery-point ID.
- `secrets.yaml` is not managed, hashed, archived, downloaded, or uploaded. If Core validation
  needs it, the disposable remote stage contains only a symlink to the existing `/config/secrets.yaml`.
  The HA REST token remains in the local process environment and never appears in argv, SSH, a
  repository file, or the deployment ledger.
- `docs/`, `attic/`, the legacy root config, `.storage`, databases, snapshots, and custom
  components are outside the managed manifest.
- Before staging, the tool compares the active remote hashes with the last verified ledger. Any
  mismatch is remote drift and blocks the operation. It repeats that comparison after staged Core
  validation, immediately before apply.
- Core validation failure removes the disposable stage and does not back up, apply, reload,
  restart, write a ledger, or actuate a device.
- A file transaction failure restores both the previous managed tree and its previous ledger
  before any reload. A post-activation canary failure is not auto-rolled back: the tool preserves
  the exact recovery point and prints the confirmation-gated command for Jeff to approve.

## Commands

Local-only preflight (no network or HA access):

```sh
make deploy-local
make test
```

Read-only remote diff (no remote write, API service, or device action):

```sh
make deploy-dry-run
```

The first run may find no ledger. If the active tree is not already byte-for-byte equal to the
candidate, name the exact commit believed to have produced the active tree:

```sh
./scripts/deploy.sh --dry-run --bootstrap-ref <40-character-prior-commit>
```

This does not trust the claim: every active managed hash must match that Git revision or the run
stops as drift. There is no way to adopt a mismatching tree.

If that first dry run passes and a real deployment is separately approved, repeat the same
immutable baseline on the mutating command:

```sh
./scripts/deploy.sh --bootstrap-ref <same-40-character-prior-commit>
```

Once a verified ledger exists, normal `make deploy` runs no longer need a bootstrap reference.

Supervised deploy, only after Jeff approves the exact operation:

```sh
export HA_URL='http://192.168.1.232:8123'
export HA_ACCESS_TOKEN='set-locally; never paste into GitHub or a command argument'
make deploy
```

The prompt requires `deploy <full-commit-sha> via <exact-service-or-no-reload>`. The tool prints
the exact A/M/D path list and
chooses one activation:

- one changed reloadable domain: its targeted reload service;
- multiple domains, `configuration.yaml`, or helpers: one full Core restart, with the reason;
- YAML dashboard files only: no Core reload.

After activation, the canonical `sensor.monitor2_temperature` must publish a newer
`last_updated`, then `scripts/verify_devices.py` must pass. Only then does the ledger become
`verified`. Deploying the same verified commit again is a read-only clean no-op.

## Rollback

Rollback is never automatic and never implied by a failed canary. Use only the recovery-point ID
printed by the failed/successful deployment and only after Jeff approves that exact ID:

```sh
export HA_URL='http://192.168.1.232:8123'
export HA_ACCESS_TOKEN='set-locally'
make rollback ROLLBACK_ID=<exact-rb-id>
```

The prompt requires `rollback <exact-rb-id> via homeassistant.restart`. The tool first refuses current drift, verifies the
snapshot hashes, stages the snapshot with the remote-only secrets symlink, runs Core validation,
and rechecks current drift. It then records the current tree as a new recovery point, restores the
requested non-secret tree, performs one full restart, and requires the same sensor/device canary.

## Supervised live acceptance still required

Local tests do not satisfy the issue's physical acceptance criteria. Record all output and elapsed
time on issue #9 while performing these separately approved operations:

1. Run the read-only dry run. If the ledger is absent, use the exact known prior commit as
   `--bootstrap-ref`. Stop on any reported mismatch; compare it with issue #4 evidence rather than
   editing the box or adopting drift.
2. In a disposable local Git worktree, commit one **valid-YAML but HA-invalid** change to the
   candidate. Run the normal supervised deploy command and type its exact commit confirmation.
   Confirm remote Core rejects the stage; confirm the output contains no apply/reload/restart;
   re-run the read-only inventory and HA status check to prove the previous commit remains active.
   Do not push the negative-test commit.
3. From the reviewed clean candidate commit, run `make deploy`, record the printed path diff and
   activation reason, and observe the newer temperature timestamp plus the full device verifier.
   Record elapsed time and the verified remote ledger.
4. Run the same clean commit a second time and confirm the tool reports a no-op without staging,
   reload, restart, or device action.
5. Test remote-drift refusal only with a separately approved, reversible test artifact chosen by
   Jeff, or use naturally observed issue #4 drift. Never hand-edit a production automation merely
   to manufacture this test. Confirm the read-only dry run reports the exact changed path and no
   write occurs.
6. With separate approval for the exact recovery-point ID, run the rollback command once. Confirm
   Core validation, restart recovery, sensor update, and device verifier. Then obtain separate
   approval before redeploying the forward candidate; rollback approval does not authorize that
   second deployment.

If any live step fails, leave the issue open, preserve the ledger/recovery ID, and stop. Do not
reload, restart, retry, edit the box, or roll back without Jeff's approval for that exact operation.
