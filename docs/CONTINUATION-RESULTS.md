# A second controller builds on the first controller's weight edit

The second controller, requested as **GPT-6.1 Sol through Codex**, received the
first controller's improved SmolLM2 checkpoint and inspected its exact numerical
diff. The earlier controller was GPT-6 Astra. The new search started from the
inherited checkpoint, not the original pretrained model.

The additional-improvement policy **failed**. The second selected patch changed
**1,152 BF16 values** relative to the inherited checkpoint.
No gradients or optimizer were used. The second patch overlaps rows changed by
the first patch, so per-patch changed-value counts must not be added as unique weights.

## All three checkpoints on the same new final set

| Checkpoint | Accuracy | Label NLL |
| --- | ---: | ---: |
| M0: original pretrained model | 398/1000 (39.8%) | 1.695823 |
| M1: first agent's checkpoint | 842/1000 (84.2%) | 0.521387 |
| M2: second agent's checkpoint | 845/1000 (84.5%) | 0.497947 |

The incremental M1-to-M2 gain is **0.3 percentage
points**: 22 corrected errors and 19 new mistakes.
The approximate paired 95% interval is -0.96 to 1.56 points;
exact two-sided McNemar p=0.755229. This measures this
fixed task subset, not broad capabilities or robustness to pretraining exposure.

The precommitted final gate required at least **+1 percentage point** over M1.
M2 did not pass and was not promoted. Label NLL decreased by 0.023440
(approximate paired 95% interval: 0.008585 to 0.038294); this does not override
the accuracy gate.

The known 56-example sentiment guard passed:
accuracy 55/56 (98.2%) before and 55/56 (98.2%) after;
NLL 0.320937 before and 0.320937 after.
Its accuracy and NLL constraints were part of selection and final acceptance.

M1 and M2 were independently reproduced through DKG with identical scores and
output hash. M0 is a supplementary local reference on the same final dataset.
The earlier first-round 38.7% -> 80.0% result used a different test subset and is
not used to calculate this incremental gain.

A supplementary local replay on the **previously exposed** first-round 1,000
examples measured M1 at 80.0% and M2 at 81.0%, with label NLL decreasing from
0.547901 to 0.531115. This diagnostic was planned before opening the new final
results, was not used for candidate selection, and is not a fresh acceptance
test. Its [record](validation-continuation/posthoc-prior-task.json) does not
retroactively change the failed final verdict.

## What the second agent saw and changed

A fresh participant first received M0, M1, the first patch and its evidence through
native DKG transport, verified hashes and independently reproduced the first
passing result. It then materialized M1 from its own received artifact store.

The handoff contained the prior controller, hypothesis, operations and aggregate
results. A bounded `inspect_diff` tool exposed actual tensor indices with before,
after and delta values computed from M0 and M1. The transcript records the second
controller reading changed values in all four label rows before its first edit.
The ordinary tensor inspector read M1's current values.

The second controller tested 15 proposals on 256 new development examples.
All were frozen before a separate 512-example selection split chose candidate
6 (the controller recommended 9).
Selection accuracy was 406/512 (79.3%) before and 413/512 (80.7%)
after. The candidate was frozen before the new 1,000-example final test.

Selected hypothesis:

> Candidate 4 recovered commercial decisions by reducing Technology but also displaced true Technology stories. Raising Business by only 3 percent alongside World by 6 percent tests a milder relative calibration while preserving Technology's inherited row. This should recover close commercial errors with less Technology suppression; sentiment preservation requires guard evaluation.

Exact operations and recorded feature vectors are in the public session. Every
new operation was relative to M1. The Rust engine reconstructed the selected M2
checkpoint byte-for-byte.

## Exact ancestry, not an informal version label

`child_spec.base == parent_spec.candidate` was checked exactly:

- M1 checkpoint manifest ID: `3ff78e37bfa3b07000d497f7673307a6bc435ade58bb0cfc509b37ae191ba91f`
- M1 file SHA256: `ffafae608659c85d5182743e8f60358eb7e8c96b10e92364c691c76c20b94a4f`
- M2 checkpoint manifest ID: `9ad722b009f00aef8cc26f517b49dbfef64fbc3cb87868117726fa3c54a91fbb`
- M2 file SHA256: `39b2edd79e527bd57494a5e6ff31fa3440802c17870163532de1920f9e826243`
- Final evaluator output: `410d8f8d55d13226feb312f715a3b87fee3ca09976be9c1de52737b293d11c44`

The parent inference-artifact mapping was preserved so changing evaluation
settings did not change the inherited checkpoint identity. DKG DerivedVersion
records form M0 --patch A--> M1 --patch B--> M2. The second proposal carries the
first proposal, patch, report, controller evidence and the verified handoff/diff.
The local UI identifies the parent proposal and inherited checkpoint.

## Preserved interruption and recovery

The Codex CLI exited during the search after nine completed attempts. The original
wrapper stopped its services and retained its failed-run record. Authentication
remained valid; the exact cause of the CLI exit was not established. The search
resumed from its transcript with the same model, data, attempts and budgets. A
resume event binds the transcript prefix and updated implementation hashes.

Recovery added bounded retries and summarized repeated older development outputs
in controller prompts; full observations remain in the audit transcript. The
baseline and newest two probes stay complete. No new selection/final information
entered controller input, and no earlier candidate was lost or silently replaced.

The final frozen child used a new local DKG pair. This recorded run therefore has
**two completed transport phases on one physical machine**,
not an uninterrupted exchange by the first pair. A separate failed reproduction
attempt stopped before model inference because the external evaluator still coupled
task configuration to checkpoint inference configuration. That contract was corrected
without changing frozen weights, data or policy; a regression test confirms that
different model inference mappings are still rejected. The failed attempt is retained
as `failed-reproduction-1.json`. Across the completed and failed network attempts,
six ephemeral identities were created. Both completed phases and their relationship
are retained. All test services stopped. A separate recovered-chain record reports
protocol success independently from the model-improvement verdict.

## Evidence and limits

- [Pre-search policy](CONTINUATION-PLAN.md) and [workflow/recovery commands](CONTINUATION-WORKFLOW.md)
- [Combined DKG chain record](validation-continuation/dkg-chain-validation.json)
- [Original interrupted phase](validation-continuation/interrupted-phase.json)
- [Final reproduction phase](validation-continuation/reproduction-phase.json)
- [Three-version comparison and paired statistics](validation-continuation/chain-comparison.json)
- [Final output including the guard](validation-continuation/heldout-output.json)
- [Verified handoff](validation-continuation/handoff.json) and [exact parent diff](validation-continuation/parent-diff.json)
- [Controller session](validation-continuation/session.public.json), [transcript](validation-continuation/transcript.public.jsonl), and [all selection results](validation-continuation/selection-report.public.json)
- [Original/public hashes](validation-continuation/manifest.json)

Source news text is replaced by SHA256 in public copies, retaining dataset IDs,
labels, numeric vectors and operations. Full artifacts were exchanged locally
through DKG; the manifest distinguishes their original hashes from redacted copies.

This is four-way forced-choice news classification with a fixed plain-text prompt,
not a general model upgrade, optimized chat baseline or fine-tuning comparison.
The new sets exclude every exact text from the prior experiment. They are fixed,
class-balanced, length-filtered subsets of a public benchmark; pretraining exposure
cannot be excluded. The sentinel guard is previously exposed and does not prove
preservation of all capabilities. DKG uses Shared Working Memory and a disposable
local EVM with the documented compatibility patch, not public-chain finality or
independent institutional validation. Physical cross-host reproduction remains open.
