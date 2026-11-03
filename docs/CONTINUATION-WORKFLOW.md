# Let a second controller improve the first controller's checkpoint

New preparations use a **0.2 percentage-point** minimum accuracy gain for both
selection and final acceptance. The recorded run originally used 1 point; its
[separate policy reassessment](continuation-policy-reassessment.json) preserves
that history and accepts the existing candidate under the revised threshold.
Reproduce this local reassessment without rerunning inference:

```sh
python3 scripts/reassess_continuation_policy.py \
  --evidence docs/validation-continuation \
  --output .runtime/continuation-policy-reassessment.json
```

A continuation inherits the previous candidate as its exact base. The next
controller receives the earlier hypothesis, operations and aggregate results, plus
an `inspect_diff` tool exposing actual tensor indices and before/after/delta values.
It must inspect a nonempty part of that diff before attempting another edit. The
ordinary `inspect` tool now reads the inherited weights. Every new attempt starts
from those weights, never from the original ancestor or the preceding trial.

This mechanism works with either existing controller backend. The included chain
validation deliberately requires a different second controller model. It transfers
the first experiment through DKG **before** launching the second controller, so the
second participant works from its own verified received artifacts.

## Complete local chain

Prepare the runtime and a first accepted AG News session as described in
[AGNEWS-WORKFLOW.md](AGNEWS-WORKFLOW.md). Then:

```sh
python3 scripts/weight_chain_validation.py \
  --parent-directory .runtime/agnews \
  --parent-session .runtime/agnews-search/selected \
  --run-dir .runtime/agnews-chain \
  --backend codex --controller-model gpt-6.1-sol
```

The command creates two fresh participants and a disposable local EVM, then:

1. A imports, reconstructs, reevaluates and publishes the frozen first experiment.
2. B begins with an empty artifact store, receives the experiment through DKG and
   independently reproduces its passing evaluation.
3. B prepares `continuation/model` from the verified received checkpoint and
   inference files. `handoff.json` links the authenticated proposal, exact parent
   checkpoint, patch, controller and evaluation. `parent-diff.json` contains actual
   sparse numerical changes computed from the received before/after checkpoints.
4. The second controller reads that context and diff, runs development attempts,
   and freezes its proposals. A separate selector chooses on new validation data.
5. B evaluates the frozen child against **M1**, publishes the second proposal,
   and A independently reproduces it and returns an evaluation/review through DKG.
6. The command verifies identical scores/output hashes and the exact checkpoint
   link, then stops its services. It preserves failed outcomes too.

The wrapper records `status` for chain/protocol reproduction separately from
`model_improvement_status`; a protocol success is not automatically a model gain.
If no candidate passes selection, the final set stays unopened and the command
fails with the proposals and selection report retained.

## Ancestry and verification

`child_spec.base == parent_spec.candidate` must hold exactly, not merely for a
filename or an informal version label. The parent inference artifact mapping is
preserved, while the new evaluation dataset/configuration/policy live in the new
EvaluationSpec. Thus a change in evaluation settings cannot accidentally break
checkpoint identity. Each native DKG DerivedVersion points to the previous
checkpoint, yielding `M0 --patch A--> M1 --patch B--> M2`.

The handoff, exact numerical diff and parent evidence are included in the child's
hash-bound evidence bundle. Preparation checks the parent proposal's authenticated
DKG author, a passing evaluation of that exact spec, and Rust reconstruction of
its patch. Subsequent reads verify artifact hashes and ancestry, recompute the
numerical diff, and reject changed bytes, forged diff values, wrong parent links
or misleading controller/hypothesis/metric context. Checkpoint file hashes remain
separate from checkpoint manifest IDs.

The task adapter currently uses single-file Transformers/Safetensors checkpoints.
It does not narrow the generic Rust engine's architecture or sharding support.
The regression and scope policies belong to this particular experiment.

## Fresh evaluation boundary

See [CONTINUATION-PLAN.md](CONTINUATION-PLAN.md) for the pre-search policy. The new
256-example development, 512-example selection and 1,000-example final subsets
exclude every exact source text used by the first experiment. Prompt and four
label-row edit scope stay fixed. The previous final metrics can be shown as
historical context, but the new final examples never enter controller input.

Selection and final acceptance require additional improvement over M1 and preserve
the known sentiment guard. Report M0/M1/M2 on the same new final set; the previous
round's 80.0% on a different set is not the denominator for incremental improvement.
A controller run is stochastic and is not guaranteed to find another improvement.
Public benchmark pretraining contamination and general capability preservation
remain outside this narrow experiment's claims.

## Recover an interrupted controller

The controller retries transient CLI interruptions at most twice after the initial
attempt. Full development observations remain in the transcript; prompts retain
the full baseline and two newest probes, with older probes summarized as metrics,
confusion matrices and high-loss errors. This bounds repeated context without
discarding audit evidence or introducing final-test information.

If the process exits between rounds, resume from its append-only transcript:

```sh
python3 scripts/run_weight_search.py \
  --directory .runtime/agnews-chain/continuation \
  --output .runtime/agnews-chain/search \
  --backend codex --controller-model gpt-6.1-sol \
  --max-probes 20 --min-probes 12 --max-rounds 32 --resume
```

Resume verifies that the model, data hashes, parent handoff, controller and budgets
are unchanged. It restores inspected tensors/diffs, activation vectors, candidates
and consumed attempts. Pending recorded actions resume without asking the controller
to replace them. A resume event binds the existing transcript prefix and the running
implementation hashes; the original commitment is retained. Search cannot reopen
once selection has started, and a finalized agent session cannot be resumed.

If the network wrapper already stopped its test services, finish the frozen child
with a new DKG reproduction pair:

```sh
python3 scripts/finish_weight_chain.py \
  --run-dir .runtime/agnews-chain \
  --reproduction-dir .runtime/agnews-chain-reproduction
python3 scripts/compare_weight_chain.py --run-dir .runtime/agnews-chain
python3 scripts/export_chain_evidence.py \
  --run-dir .runtime/agnews-chain --output .runtime/public-chain-evidence
```

Recovery preserves the original failed-run record and writes a separate combined
record. It explicitly reports two transport phases and four ephemeral identities,
not uninterrupted work by the original pair. The inherited checkpoint and original
authenticated receipt stay the same. The comparison measures the original M0
locally; M1/M2 and the guard come from the independently reproduced final output.
Use `--failed-reproduction PATH` on `finish_weight_chain.py` to retain any additional
failed reproduction attempts and their identities. The recorded run needed one
such attempt before separating external task configuration from model inference
configuration; its total includes six ephemeral identities across three attempts.

## Replay the recorded two-patch chain

Once the public continuation evidence is present, reconstruct both checkpoints
without calling either controller:

```sh
python3 scripts/replay_weight_session.py \
  --session docs/validation-agnews/session.public.json \
  --base .runtime/model-cache/model/model.safetensors \
  --output .runtime/replayed-m1.safetensors
python3 scripts/replay_weight_session.py \
  --session docs/validation-continuation/session.public.json \
  --base .runtime/replayed-m1.safetensors \
  --output .runtime/replayed-m2.safetensors
```

Each command checks its exact base file hash, changed-value count and candidate
file hash. This reproduces the numerical chain independently of future controller
responses. The first recorded AG News checkpoint is the inherited M1 in this run.
