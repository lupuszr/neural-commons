# Run the guarded news-classification experiment

This is a task-specific edit to four vocabulary embedding rows of an unmodified
pretrained language model. It does not change architecture, prompts or datasets.
The controller chooses the edits using development observations, and the host
enforces the allowed named tensor regions. The Rust patch engine is unchanged.

After installing the optional Python dependencies and preparing Rust/DKG as in
[WEIGHT-AGENT.md](WEIGHT-AGENT.md):

```sh
python3 scripts/prepare_weight_experiment.py --directory .runtime/model-cache
python3 scripts/prepare_agnews_experiment.py \
  --model .runtime/model-cache/model --directory .runtime/agnews
python3 scripts/run_weight_search.py \
  --directory .runtime/agnews --output .runtime/agnews-search \
  --backend codex --controller-model gpt-6-astra
python3 scripts/weight_dkg_validation.py \
  --directory .runtime/agnews --session .runtime/agnews-search/selected \
  --run-dir .runtime/agnews-dkg
```

Preparation checks the original model file against the pinned upstream SHA256.
The AG News dataset revision, fixed-seed splits, length filter, prompt, metric
policy, allowed edit regions and sentiment guard are all fixed before the controller
starts. See [AGNEWS-EXPERIMENT-PLAN.md](AGNEWS-EXPERIMENT-PLAN.md).

`run_weight_search.py` exposes only development examples to the controller, saves
all proposals, then selects using a separate validation split. It never evaluates
the final news test. The optional activation contrast tool computes a supervised
class-mean difference from the base model's final hidden states; the agent chooses
whether to use it, the destination and the scale. This is not gradient training.

Selection and final evaluation both require the previously exposed 56-example
sentiment guard to preserve accuracy and NLL. The `guarded_accuracy/v1` metric
returns actual news accuracy when the guard passes, or zero when it fails. The
output artifact retains both actual task metrics and guard metrics in either case.

Only after a candidate is frozen does the DKG validation run the 1,000-example
news test subset. It creates fresh local participants, transfers the checkpoint,
patch, tokenizer, configuration, guard data and provenance through native DKG
transport, and independently reproduces the evaluator output. It stops its services.

Use `--backend openai` with `OPENAI_API_KEY` for the API controller. Codex uses the
existing login. New controller runs may choose different edits and are not guaranteed
to improve the model. `replay_weight_session.py` reconstructs a recorded candidate
without a new controller call, using its recorded numeric operations and vectors.

For the exact recorded candidate, after preparing the original model:

```sh
python3 scripts/replay_weight_session.py \
  --session docs/validation-agnews/session.public.json \
  --base .runtime/model-cache/model/model.safetensors \
  --output .runtime/recorded-agnews-candidate.safetensors
```

The command verifies the pristine base, changed-value count and byte-exact
candidate hash. It needs neither a controller login nor the original news text.
Public evidence is redacted and has different file hashes from the original DKG
artifacts; the manifest records both. The workflow above creates a new full
experiment, while this replay reconstructs the recorded checkpoint specifically.

Claims are limited to this fixed forced-choice task and this regression guard.
The baseline uses the same fixed plain-text completion prompt as the candidate.
No comparison against prompt tuning, full fine-tuning or optimized chat templates
is implied. Public benchmark contamination during pretraining cannot be excluded.
