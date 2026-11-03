# An agent weight edit improves news classification

An authenticated Codex controller, requested as `gpt-6-astra`, proposed direct
numeric edits to an unmodified pretrained **SmolLM2-135M-Instruct** checkpoint.
The selected edit changed **2,268 BF16 values** out of 134,515,008 stored parameters.
It improved a fixed four-way news-classification task while preserving a required
sentiment regression guard. No gradients, optimizer or generated training program
were used.

## Final result

| Measure | Original checkpoint | Agent candidate |
| --- | ---: | ---: |
| AG News accuracy, 1,000 held-out examples | 387/1,000 (38.7%) | 800/1,000 (80.0%) |
| News label NLL, lower is better | 1.796822 | 0.547901 |
| Sentiment guard accuracy, 56 known examples | 55/56 (98.2143%) | 55/56 (98.2143%) |
| Sentiment guard label NLL | 0.320937 | 0.320937 |
| Precommitted guarded task policy | Reference | Passed |

The accuracy gain is **41.3 percentage points**: 481 mistakes corrected and 68 new
mistakes introduced, a net gain of 413 correct answers. Its approximate paired 95%
interval is **+37.49 to +45.11 points**; exact two-sided McNemar p is 1.31e-77.
These describe this fixed task subset, not general model capability. NLL fell by
1.248922, with an approximate paired 95% interval of 1.135606 to 1.362238.

## What the controller did

The operator fixed an edit scope of four rows in `model.embed_tokens.weight`,
corresponding to the single-token labels ` World`, ` Sports`, ` Business` and
` Technology`. The architecture ties these input embeddings to output weights.
The generic Rust patch engine did not gain architecture-specific logic.

The controller inspected weights and tested 13 proposals on 128 development
examples. It requested supervised activation contrasts: for each class, the
unit-normalized difference between the base model's final hidden-state mean for
that class and the mean for the other classes. The controller chose the scales
and hypotheses. The host provided the statistic and executed the arithmetic;
this uses labeled development data and an engineered contrast tool, not an
unaided discovery of the entire editing algorithm.

The selected operations are `new_row = scale * base_row + add_scale * contrast`:

| Label | Token ID | Scale | Contrast coefficient |
| --- | ---: | ---: | ---: |
| World | 2260 | 0.80 | 0.26 |
| Sports | 15278 | 1.00 | 0.14 |
| Business | 8460 | 1.13 | 0.15 |
| Technology | 5804 | 1.20 | 0.20 |

Each row has 576 elements. BF16 rounding leaves 36 of the 2,304 targeted values
unchanged, so 2,268 stored values actually changed. Every other checkpoint byte,
including its header, was preserved. Recorded vectors and operations reconstruct
the candidate without a new controller call.

## Split discipline and selection

The pinned AG News revision is `eb185aade064a813bc0b7f42de02595523103ca4`.
Fixed-seed, class-balanced subsets contain 128 development, 256 selection and
1,000 final-test examples. The final subset comes from the official test split,
with a prompt-length filter of at most 220 tokens. No model score informed that
filter. The actual three subsets have no identical source texts in common.

The controller saw development observations only. All 13 proposals were frozen
before the separate selector evaluated them. Candidate 12 won the precommitted
rule: highest selection accuracy, then lowest NLL, among candidates improving
accuracy by at least one point, not worsening NLL, and passing the sentiment
guard. Selection accuracy rose from 108/256 to 213/256. The chosen checkpoint was
frozen before the final test. No edit was tuned against the final result.

The final policy required at least 70% accuracy and at least a two-point gain,
plus no sentiment-guard accuracy loss or NLL increase beyond 1e-6. The evaluator's
`guarded_accuracy/v1` returns zero if the guard fails, retaining actual metrics in
the detailed output. The guard is thus part of both participants' acceptance
contract. Its 56 previously exposed examples are a regression check, not an
independent benchmark.

A supplementary local check on all 872 previously exposed SST-2 examples also
preserved the original model's **673/872 accuracy and 0.530379 NLL**. Every recorded
prediction and label logit was identical. None of the four edited token IDs occurs
in those prompts, and neither sentiment output row was edited. This explains the
preservation; it is not broad capability testing. This check was not used for
selection or included in the DKG acceptance contract. Its [output is retained](validation-agnews/posthoc-regression.json).

Model revision: `12fd25f77366fa6b3b4b768ec3050bf629380bac`. The original file was
verified against the pinned upstream SHA256:
`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.

## DKG reproduction

Two fresh local DKG participants, with separate identities and stores, reproduced
the same successful verdict, scores, guard result and evaluator-output hash:
`c420c20aedb4b43f3c048da66b801b681849045691358b643a34f0e197e28310`.

Participant B started without artifacts. It received the model, patch, tokenizer,
configuration, data, policy and controller provenance through native DKG transport,
verified hashes, reconstructed the checkpoint and ran a separate evaluator
process. Participant A retrieved B's evaluation and review, checking author and
proposal relationship. Services were stopped after validation.

The Rust patch reconstruction and a standalone numeric replay matched candidate
file SHA256 `ffafae608659c85d5182743e8f60358eb7e8c96b10e92364c691c76c20b94a4f`.

- [Workflow](AGNEWS-WORKFLOW.md) and [pre-search plan](AGNEWS-EXPERIMENT-PLAN.md)
- [DKG validation](validation-agnews/dkg-validation.json)
- [Final predictions and guard](validation-agnews/heldout-output.json)
- [Paired statistics](validation-agnews/summary.json)
- [Controller session](validation-agnews/session.public.json)
- [Controller transcript](validation-agnews/transcript.public.jsonl)
- [All selection results](validation-agnews/selection-report.public.json)
- [Original/public artifact hashes](validation-agnews/manifest.json)

Public evidence replaces source news text with hashes while retaining dataset IDs,
labels, predictions, operations and activation vectors. Full artifacts were
exchanged locally through DKG. The manifest distinguishes original artifact hashes
from redacted public-file hashes. The pinned source and recorded vectors support
reproduction without redistributing the full source text.

## Scope and earlier failures

This is forced-choice classification using one fixed plain-text completion prompt,
identical before and after editing. The baseline is not an optimized chat prompt.
There is no comparison against prompt tuning, fine-tuning, other classifiers or
state-of-the-art results, and no demonstrated improvement in free-form generation.
Public benchmark exposure during pretraining cannot be excluded. Broader capability
preservation remains untested.

The [original confidence-scaling edit failed](WEIGHT-AGENT.md), and the
[SST-2 edit](SST2-RESULTS.md) improved its own task but severely damaged the earlier
sentiment probe. Both remain recorded. That regression motivated this new task's
restricted edit scope and mandatory guard.

These DKG participants ran on one physical machine using Shared Working Memory,
a disposable local EVM and the documented local opaque-artifact compatibility
patch. This is local reproducibility, not public-chain finality or independent
institutional validation. The earlier [Mac mini test](CROSS-HOST.md) is separate;
this LLM result has not yet been reproduced across two physical machines.
