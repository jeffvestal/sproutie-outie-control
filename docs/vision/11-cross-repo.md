# 11 — Cross-repo rules: public code, private state

Sproutie spans two repositories with different visibility, and that asymmetry is not cosmetic —
it determines what an agent can read, where specs must live, and where tent state is allowed to
land.

| Repo | Visibility | Holds | Pipeline |
|---|---|---|---|
| `jeffvestal/sproutie-outie-control` | **public** | HA config, the Brain, recipes, architecture docs | none yet — manual sessions |
| `jeffvestal/nat` | **private** | the Nat iOS/Mac apps, personal state, grow status | Express Issue |

## Rule 1 — dependencies point private → public, never the reverse

A worktree checked out on the **public** repo cannot read the **private** one. So:

- **Specs, schemas and contracts live in the public repo.** The private app links to them.
- The private repo may depend on anything public. The public repo may depend on nothing private.
- A public issue that links to a `jeffvestal/nat` blob renders as a 404 for everyone but Jeff.
  Describe the substance in the public issue and treat the private link as a convenience, not as
  the carrier of meaning.

**Worked example.** `status/tent.yaml` is written by the Brain (public) and read by the app
(private). The contract therefore lives in **`06-brain-spec.md` §2**, public. The app's fixture,
model types and tests live in `nat`, private. If the app needs a field the spec lacks, that is a
change to the *public* spec, raised as an issue — never a private-side invention that leaves the
two implementations silently disagreeing.

The inverse would be a trap: a contract authored in `nat` would be invisible to the component
that has to produce the file.

## Rule 2 — UI previews are the one sanctioned exception

Nat's UI mockups are built from private app source and its design tokens, so they cannot move to
the public repo. They stay in `nat/renders/ui-previews/`, referenced from public issues by
commit-pinned URL.

Accept that those links 404 publicly. The public issue must still carry enough prose that a
reader who cannot open the preview understands what was decided and why.

## Rule 3 — tent state lands in the private repo

The Brain publishes `status/tent.yaml` plus snapshot thumbnails. **It pushes them into
`jeffvestal/nat`, not into the public repo.**

Why that direction:

- **The app already syncs `nat`.** Tent status becomes another file beside `brain.md` and
  `today-cards.yaml` — no second sync path, no new client code, and card actions reconcile
  through the existing `today-actions.yaml` flow.
- **Tent state stays private.** Snapshot timestamps, light schedules and camera health are
  operational detail about a room in the house. Low stakes, but there is no reason to publish
  them, and it costs nothing to keep them private.
- **The public repo stays code and docs only.** No state file in it means no accidental leak
  through a state file, and no history churn from a process that writes every few minutes.

The Brain needs a write credential for a private repo (deploy key or fine-grained PAT, scoped to
`nat` contents). That credential lives in the Brain's environment on the HA box — **never in the
public repo**, which is exactly the mistake `00-current-state.md` §4 documents.

> If Sproutie is ever federated (`08-moonshots.md` §5 — the Colony), the shareable artifacts are
> **recipes and the protocol**, both already public. Grow journals stay private per household.
> Nothing in this rule blocks that.

## Rule 4 — cross-repo blockers are written in words, in both issues

GitHub sub-issues link across repositories, and the epic uses that. But the **Express Issue
dispatcher does not traverse those links** — it scans `jeffvestal/nat` and `jeffvestal/edith`
only, and it will happily claim an issue whose real-world prerequisite lives in the other repo.

So every cross-repo dependency is stated as prose in *both* issues, naming the blocking issue and
the condition that clears it. Do not rely on the graph to stop a run.

Current instance: `nat#234` (Grow tab) is blocked by `nat#236` (Standup demotion) — both in the
private repo — while its *spec* lives here in the public one. Three repos' worth of relationships
across two repos; write it down every time.

## Rule 5 — pipeline coverage is asymmetric, so plan around it

Express Issue covers `nat` and `edith`. The sproutie repo has no dispatcher, so **every issue
here needs a manually launched session** until that changes.

Practical consequence for sequencing: iOS work (R4) can run through the pipeline today, while
R0–R3 cannot. That is a reason to let the app lead — building the consumer first also pins down
what the Brain must publish — but it is a scheduling artifact, not an architectural preference.

To change it, add this repository to the dispatcher's scan list. `#4` (archive the running HA
config) is the best first candidate: read-only, no console access, and it unblocks `#6` and `#10`.
