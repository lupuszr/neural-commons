# SST-2: task improvement with an unacceptable regression elsewhere

This experiment produced a real, task-specific accuracy gain, independently
reproduced through DKG. A supplementary check then exposed a large regression on
the previously used synthetic sentiment task. **Do not treat this checkpoint as a
general model upgrade.** Both outcomes are preserved.

The original pretrained SmolLM2 checkpoint was unchanged before editing. Codex
(requested GPT-6 Astra) proposed six token-semantic edits, then twelve edits using
a supervised development activation contrast. Each search froze its proposals
before selection; the second search was added after the first selection result,
while the final set remained unopened. The 256-example selection split chose candidate 10 from the
second search; its final weights were frozen before the 872-example final set was
evaluated. The final test was not used to choose another SST-2 candidate.

The edit changed 1,108 stored BF16 values in two embedding rows. It used the
normalized difference of positive/negative development hidden-state means:
`positive = 1.02 * original_positive + 0.15 * contrast`,
`negative = original_negative - 0.15 * contrast`. No gradients or optimizer were used.

| Final SST-2 measure | Original | Candidate |
| --- | ---: | ---: |
| Accuracy | 673/872 (77.1789%) | 694/872 (79.5872%) |
| Label NLL | 0.530379 | 0.484548 |
| Precommitted task policy | Reference | Passed |

The net gain is 21 correct predictions: 74 errors corrected and 53 previously
correct predictions broken. The accuracy difference is +2.4083 percentage points.
Its approximate paired 95% interval is −0.1212 to +4.9377 points; exact two-sided
McNemar p=0.07553. Accuracy evidence alone is not strong at the conventional 5%
level. Mean NLL reduction is 0.045831, with an approximate paired 95% interval of
0.032075 to 0.059587. These intervals describe this fixed dataset, not broad capability.

The test consisted of all 872 official SST-2 validation examples, reserved as this
experiment's final holdout. It was not the hidden GLUE test. See the
[preparation and selection plan](SST2-EXPERIMENT-PLAN.md) and
[reproducible workflow](SST2-WORKFLOW.md).

## Regression found after the final test

On the previously exposed 32-example synthetic sentiment set, accuracy dropped
from **31/32 to 20/32**, and NLL rose from **0.331622 to 0.588203**. This was a
supplementary local diagnostic, not an unseen benchmark and not part of the
original SST-2 acceptance policy. We did not hide the regression or use that
SST-2 final result to tune another SST-2 patch.

This motivated a separate [AG News experiment](AGNEWS-EXPERIMENT-PLAN.md), with a
new final test, a restricted edit region and a sentiment guard included in both
selection and the immutable final evaluator contract.

## Reproduction and evidence

Two separate local DKG daemons with fresh participant identities and artifact
stores reproduced the same task verdict, metrics and evaluator-output hash:
`c0a323251187f98fb94332a53f8296053286675c1e4d6c61f2cbe95c7a74aa1a`.
The Rust engine reconstructed the selected checkpoint exactly, and a separate
numeric replay reproduced file hash
`8b5fb0c0209590c98af11268023d130ba1868db235e9665eb5f144f64aab14c6`.

- [DKG validation](validation-sst2/dkg-validation.json)
- [Final predictions and metrics](validation-sst2/heldout-output.json)
- [Paired statistics](validation-sst2/summary.json)
- [Controller session](validation-sst2/session.public.json)
- [Controller transcript](validation-sst2/transcript.public.jsonl)
- [All selection results](validation-sst2/selection-report.public.json)
- [Regression diagnostic](validation-sst2/posthoc-regression.json)
- [Original/public artifact hashes](validation-sst2/manifest.json)

Public copies redact source review text while retaining dataset IDs, text hashes,
labels, predictions, numeric edits and activation vectors. Full artifacts were
exchanged locally through DKG. Pinned source data and replay scripts allow the
numeric candidate to be reconstructed without a controller call.

These are local participants on one physical machine, using Shared Working Memory
and a disposable local EVM. They do not establish public-chain finality or
independent institutional validation. Public benchmark pretraining contamination
cannot be excluded.
