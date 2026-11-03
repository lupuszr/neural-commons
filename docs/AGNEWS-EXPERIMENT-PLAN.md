# News classification with a sentiment-preservation guard

The SST-2 edit passed its task-specific final policy but substantially degraded
the old synthetic sentiment probe. Preserve that result, including the regression;
do not present it as a general upgrade or tune against its now-exposed final set.

Use a new task and previously unused final set: AG News four-class topic
classification. Keep the original pretrained SmolLM2 checkpoint, prompt and data
fixed. The agent can edit only the four named task-label embedding rows (World,
Sports, Business, Technology), with host-enforced region checks. The Rust engine
remains generic; this edit scope is an experiment-specific operator policy.

The dataset revision, seeds and filtering rule are fixed before controller output.
Use 32/class training examples for development, a disjoint next 64/class for
selection, and 250/class from the official test split for final evaluation. Select
by fixed-seed shuffle, exact text deduplication within class and prompt length at
most 220 tokens. Never filter by model score. This is a 1,000-example test subset,
not a claim about the entire official test set.

Run at most 16 edit attempts and 28 controller rounds, with at least 12 attempts.
The controller receives development examples and may inspect tensors and request
development activation contrasts (including one class versus the rest). No gradients,
optimizer, generated training program, selection data or final-test data are provided.

Both selection and final evaluation include all 56 previously exposed synthetic
sentiment examples as a regression guard. Require no accuracy loss and no label-NLL
increase beyond numerical tolerance (1e-6). This is a known regression check, not
an independent benchmark. Bind its files and policy before the controller starts.

Selection requires at least one percentage point of news accuracy improvement,
non-worsening news NLL, and a passing sentiment guard; rank by accuracy, then lower
NLL, then candidate ID. Freeze that candidate before final evaluation. Final
acceptance requires at least two percentage points of news accuracy improvement,
accuracy at least 70%, and a passing guard. Report NLL and paired uncertainty too.

The evaluator's `guarded_accuracy/v1` returns the measured candidate accuracy when
the guard passes, or zero when it fails. Detailed output always retains the actual
news and guard metrics. This makes the guard part of the immutable evaluator
contract and of both DKG participants' verdicts, rather than an informal note.

Independently reproduce the selected patch, final result and guard through native
DKG transport between two fresh local participants. Preserve all failed candidates,
all previous experiments and the distinction between task performance, statistical
uncertainty, regression checks and general model capability.

Source: https://huggingface.co/datasets/fancyzhx/ag_news, revision
`eb185aade064a813bc0b7f42de02595523103ca4`. Public benchmark contamination during
pretraining cannot be excluded. Four-way forced-choice accuracy is not a test of
unrestricted generation or broad capabilities.
