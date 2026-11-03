# Second weight-space experiment: improve decisions

The first agent run amplified confidence without changing a single classification
decision and failed held-out evaluation. The next experiment targets accuracy on
real SST-2 review text, using the original pretrained SmolLM2 checkpoint.

Before the controller starts, fix the dataset revision and split seed, prompt,
labels, model revision, metric policy, selection policy and budgets. Do not select
examples using model scores. Use 128 class-balanced examples from the SST-2 train
split for controller feedback and a disjoint 256-example train-derived selection
split. Reserve all 872 examples of the official SST-2 validation split for the
final evaluation. This is our experiment's holdout, not the hidden GLUE test set.

The Codex controller sees only the 128 development examples. It has at most 16
experiment attempts and 24 decision rounds, with the same direct numerical weight
tools and no gradients. Pure global temperature scaling cannot improve accuracy.

After the controller stops, an independent selector evaluates its frozen proposals
on the selection split. Eligible proposals must improve selection accuracy by at
least one percentage point and must not worsen binary-label NLL. Rank them by
accuracy, then lower NLL, then candidate ID. Preserve all proposals and all scores.
If no proposal qualifies, do not open the final test.

Freeze the selected weights before final evaluation. The final policy requires
accuracy of at least 70% and an improvement of at least two percentage points.
Report NLL, corrected versus newly broken predictions, and paired statistical
uncertainty alongside the primary metric. Do not treat a threshold pass as proof
of general capability improvement. If the final result fails, preserve the failure;
never tune against that final result and present a retry as an untouched test.

The selected candidate must be reconstructed exactly through the Rust patch
engine and independently evaluated by a fresh DKG participant. Share the agent
transcript, pre-run commitment, validation selection and held-out result through
DKG. Distinguish local participants from different physical machines.

Source: https://huggingface.co/datasets/stanfordnlp/sst2 at revision
`8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb`. Public benchmark contamination during
pretraining cannot be excluded. Train-derived development/selection examples may
contain related phrases even after exact text deduplication.

## Search extension before final evaluation

The first six-proposal search produced a small eligible selection gain. Before
opening the final holdout, run a second development-only search with a read-only
activation-contrast tool: the unit-normalized difference of the base model's final
hidden-state means for the two development classes. The agent chooses whether and
how strongly to add this supervised statistic to a tensor slice. This is a
data-informed, gradient-free edit, not a claim of discovering weights without data.

The second search allows 28 decision rounds and 16 edit attempts, with a minimum
of 12 attempts before finalization. It receives neither selection examples nor
selection scores. Preserve both searches. Choose the strongest eligible candidate
across the two searches using the same selection accuracy/NLL ordering; break a
remaining tie by search order, then candidate ID. Only then open the final holdout.
