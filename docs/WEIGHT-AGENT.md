# An LLM agent directly edits another LLM's weights

Neural Commons now includes a controller that reads named tensors, proposes
numerical edits, tests them on development examples, and freezes one candidate.
It does not generate training code or use gradients. The Rust engine then creates
and reconstructs the patch. A separate evaluator tests the frozen candidate;
another DKG participant independently repeats that evaluation.

This is the missing central experiment from the original concept. The earlier
Iris run used ordinary gradient training and did not implement this controller.

For agents building on each other's work, see [sequential continuation](CONTINUATION-WORKFLOW.md).
An inherited run exposes the prior diff through `inspect_diff`, starts every
candidate from the previous accepted checkpoint, and binds the parent proposal,
checkpoint and exact diff into its commitment and DKG evidence.

The latest [guarded AG News result](AGNEWS-RESULTS.md) improved held-out task
accuracy from **38.7% to 80.0%** by editing **2,268 BF16 weights**, preserving the
mandatory sentiment guard. See [its workflow](AGNEWS-WORKFLOW.md) for a development /
selection / final-test experiment. The original failed experiment below remains
part of the record, as does the [SST-2 edit with a regression](SST2-RESULTS.md).

## Two controller backends

| Backend | Authentication | Execution |
| --- | --- | --- |
| `codex` | Existing `codex login` (including ChatGPT login) | Noninteractive `codex exec`, structured JSON decisions |
| `openai` | `OPENAI_API_KEY` | Responses API, structured JSON decisions |

Both use the same host-enforced tools: inspect a tensor, tokenize text, read a
development activation contrast, propose numeric slice transformations, and finalize
a tested candidate. Each edit computes
`base_destination * scale + base_source * add_scale`. Sources always refer to the
pristine base, or an explicitly recorded read-only activation statistic. The
contrast tool returns the unit-normalized difference of base-model final hidden
state means for two development classes. This uses labeled development data; it is
not a claim of discovering an edit without supervision. The controller chooses
tensors, regions, coefficients and hypotheses.
There is no prescribed winning edit, generated shell command or optimizer.

The Codex adapter uses an ephemeral empty working directory, ignores user/project
configuration, disables shell, apps, browser and other native tools, and requests
a JSON-schema response. It uses the existing login without reading or exporting
the credential. The API adapter has no native tools. The host supplies development
observations only, never held-out examples or their path.

The live run below exercised **Codex**. The API adapter passed its mocked request/
response contract test, but live API validation was unavailable because the
environment's API key was invalid. There is no silent backend fallback.

## Run an experiment

Install the optional Python adapter dependencies in your selected Python environment:

```sh
python3 -m pip install -r requirements-weight-agent.txt
cargo build --locked --workspace
codex login status
python3 scripts/prepare_weight_experiment.py --directory .runtime/my-weight-experiment
```

Preparation downloads a revision-pinned, approximately 269 MB Safetensors checkpoint
of `HuggingFaceTB/SmolLM2-135M-Instruct` and its inference files. The demo adapter uses
CPU float32 inference; the stored weights and edits remain BF16. It needs enough
RAM for model inference. This does not introduce a file-size cap in the Rust engine.

```sh
EXPERIMENT="$PWD/.runtime/my-weight-experiment"
HELDOUT_SHA=$(shasum -a 256 "$EXPERIMENT/heldout.json" | cut -d ' ' -f 1)
POLICY_SHA=$(shasum -a 256 "$EXPERIMENT/policy.json" | cut -d ' ' -f 1)
target/debug/nc agent \
  --backend codex --controller-model gpt-6-astra \
  --model "$EXPERIMENT/model" \
  --config "$EXPERIMENT/config.json" \
  --development "$EXPERIMENT/development.json" \
  --source "$EXPERIMENT/source.json" \
  --heldout-sha256 "$HELDOUT_SHA" --policy-sha256 "$POLICY_SHA" \
  --output "$EXPERIMENT/session"
```

For the API backend, set `OPENAI_API_KEY` in the process environment and replace
`--backend codex` with `--backend openai`. Select a model available to your account
using `--controller-model`. The host never stores the key in transcripts.

Default budgets are 16 controller rounds, 8 experiment attempts and 2,000,000 edited
elements per candidate, configurable through CLI options. Each response can request
up to four actions; inspections expose at most 256 raw values. Transform coefficients
must be finite and within ±100. Invalid attempts consume experiment budget. All
successful candidates and rejected actions remain in `transcript.jsonl`.
`--min-probes` can require further exploration before finalization. A separate
selection split and fixed selection policy can choose among all frozen proposals
without exposing final-test examples to the controller.

The development dataset, target file, held-out dataset and policy hashes are committed
before the first controller response. The selected checkpoint and transcript hashes
are frozen before evaluation. An output directory cannot be reused accidentally.

Run the independent DKG check after preparing the DKG runtime with `scripts/setup.py`:

```sh
python3 scripts/weight_dkg_validation.py \
  --directory "$EXPERIMENT" --session "$EXPERIMENT/session" \
  --run-dir .runtime/my-weight-dkg-check
```

The validation fetches current `origin/testnet-canary`, requires the isolated build
to match it, launches two DKG daemons and a disposable local EVM, imports and applies
the patch using Rust, evaluates on held-out examples, transfers the proposal, and
has a fresh participant reproduce it. It stops its services on completion.

`EvaluationSpec.evidence` binds content-addressed session, transcript, commitment,
development data and runtime manifest artifacts. These are included in the native
DKG transfer. Model configuration and tokenizer files are inference artifacts shared
by both checkpoints. Evaluator commands remain operator-selected; a proposal cannot
choose executable code. Detailed predictions are stored in the evaluator output hash.

## Recorded result: an actual edit, rejected by evaluation

Date: 2026-11-03. Controller: requested `gpt-6-astra` through authenticated Codex CLI.
Target: unmodified SmolLM2-135M-Instruct, revision
`12fd25f77366fa6b3b4b768ec3050bf629380bac`, 134,515,008 stored parameters.

The controller inspected `model.norm.weight`, tested scale factors 4, 32 and 64,
and selected 64. An attempted scale of 128 was rejected by the tool policy. The
selected patch changed **576 BF16 parameters**. No gradients were computed.

| Measure | Original checkpoint | Agent candidate |
| --- | ---: | ---: |
| Development accuracy (24 examples) | 24/24 | 24/24 |
| Development binary-label NLL (lower is better) | 0.306690 | 0.000001113 |
| Held-out accuracy (32 examples) | 31/32 | 31/32 |
| Held-out binary-label NLL (lower is better) | 0.331622 | 1.048956 |
| Held-out policy | Reference | **Failed** |

The edit amplified confidence without improving classification. The same held-out
mistake became much more confident, worsening NLL. The controller did not see these
held-out examples or results before finalization. We did not tune another candidate
against the now-exposed test set.

Both local participants reproduced the exact metrics and output artifact
`973e43dea7ca237e0bbad6e760f7cb1d984b4f67b23170d82f31b5aec944d52d`.
The DKG protocol validation passed; the model improvement policy failed. These are
different outcomes. The candidate was not selected as an accepted model version.

Evidence: [DKG validation](validation-weight-agent/dkg-validation.json),
[controller session](validation-weight-agent/session.json),
[complete controller transcript](validation-weight-agent/transcript.jsonl),
[held-out predictions](validation-weight-agent/heldout-output.json),
[pre-run commitment](validation-weight-agent/commitment.json).

This is a small hand-written binary-label probe, not a public benchmark, free-form
generation evaluation, broad capability gain, or reproduction of the research's
Qwen results. The LLM experiment ran on **one physical machine with two independent
local participants**. The earlier [laptop/Mac mini validation](CROSS-HOST.md) remains
a separate synthetic transport and repair test. Neither is public-chain finality.

The Rust registry stays architecture independent. This first controller adapter
loads a single-file Transformers checkpoint and exposes affine slice edits; it is
not a universal autonomous weight-programming system. Other architectures, edit
operators, tasks and evaluators can be added without specializing the Rust engine.

Original inspiration: [Rikiya Takehi's post](https://x.com/rikiyatakehi/status/2117313742891327994)
and [Sparks of Weight-Space Programming](https://rikiyat.github.io/blog/weight-space-programming/).
