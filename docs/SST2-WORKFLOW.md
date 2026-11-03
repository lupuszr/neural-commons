# Running the accuracy experiment

This workflow uses real SST-2 movie-review examples and an untouched pretrained
SmolLM2-135M-Instruct checkpoint. It measures forced-choice sentiment accuracy,
not free-form generation or general intelligence. See the
[experiment and selection plan](SST2-EXPERIMENT-PLAN.md).

Install `requirements-weight-agent.txt`, build Rust, and prepare the DKG runtime
as described in [WEIGHT-AGENT.md](WEIGHT-AGENT.md). Then:

```sh
# Downloads the pinned model; the small fixture files are not used by SST-2.
python3 scripts/prepare_weight_experiment.py --directory .runtime/model-cache
python3 scripts/prepare_sst2_experiment.py \
  --model .runtime/model-cache/model --directory .runtime/sst2

# Search and selection only. The controller does not receive the final test.
python3 scripts/run_weight_search.py \
  --directory .runtime/sst2 --output .runtime/sst2-search \
  --backend codex --controller-model gpt-6-astra

# Run once after selecting the candidate; independently reproduce through DKG.
python3 scripts/weight_dkg_validation.py \
  --directory .runtime/sst2 --session .runtime/sst2-search/selected \
  --run-dir .runtime/sst2-dkg
```

`--backend openai` uses `OPENAI_API_KEY`; `codex` uses the existing Codex login.
Model access depends on the selected account. The workflow does not silently
switch backends. A new search can produce different controller decisions and is
not guaranteed to improve the model.

The prepared split is deterministic: 128 development and 256 selection examples
from SST-2 train, with all 872 official validation examples reserved for the final
test. Exact train text duplicates are removed, and development/selection IDs are
disjoint. Related phrases can still occur in those train-derived subsets. Public
benchmark examples may have appeared in model pretraining; this cannot be excluded.

The agent can inspect weights and request a normalized difference of base-model
hidden-state class means from the development examples. It chooses numeric slice
edits using either original weights or that recorded activation vector. These are
supervised, gradient-free edits; there is no optimizer or generated training code.

All candidate operations are frozen before selection. The selector ranks eligible
candidates by accuracy, then NLL, then ID. Selection requires at least one percentage
point of accuracy improvement and no NLL regression. The final policy requires at
least two percentage points of improvement and accuracy of at least 70%. Neither
threshold is changed after seeing final results.

The final evaluator emits per-example IDs, text hashes, labels and predictions.
`scripts/summarize_weight_result.py` computes corrected/regressed counts, an
approximate paired confidence interval and exact two-sided McNemar p-value.
These describe this fixed task, not performance across tasks or model families.

For byte-exact replay of a recorded edit, use its session artifact, original model
file and a new destination:

```sh
python3 scripts/replay_weight_session.py \
  --session path/to/session.json \
  --base .runtime/model-cache/model/model.safetensors \
  --output .runtime/replayed.safetensors
```

Replay needs no controller login, gradient calculation or dataset labels. It checks
the original file hash, reconstructs the numeric edits, and requires the output
hash and changed-parameter count to match the recorded candidate. The normal DKG
workflow separately verifies reconstruction through the Rust patch engine.
