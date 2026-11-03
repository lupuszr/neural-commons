# Weight-space agent: restore the central experiment

The intended workflow includes an LLM controller reading and directly editing a
different language model's parameters. The existing registry, Iris training run,
and DKG exchange do not implement that step. This iteration adds it explicitly.

1. Run an operator-selected controller through the Responses API. Give it bounded
   tools to inspect named tensors, identify tokens, propose numeric edits, and
   evaluate candidates on a development split. No generated shell commands,
   gradients, optimizer, or access to held-out examples through these tools.
2. Use an unmodified, revision-pinned pretrained language model as the baseline.
   The first experiment is a narrow sentiment-label task on SmolLM2-135M-Instruct;
   this is a replaceable experiment adapter, not a restriction on the Rust engine.
3. Fix the task, held-out dataset hash, evaluation policy, and budgets before the
   controller starts. Record every model response, edit, and development result.
   Freeze the selected candidate before running held-out evaluation once.
4. Register the original and edited checkpoints, produce/apply the patch using
   Rust, and bind the controller transcript and experiment commitment into the
   evaluation specification. Transfer these artifacts through DKG. A second
   participant loads the model and independently evaluates the same candidate.
5. Preserve failures. A completed edit is not evidence of an improvement. Report
   actual held-out metrics, changed parameters, model/controller identities,
   runtime, dataset limitations, and the scope of independent reproduction.
6. Correct the article draft to distinguish this experiment from Iris gradient
   training and synthetic cross-machine transport tests. Do not publish it.

Acceptance: a real LLM controller produces a non-empty weight edit to another
real pretrained language model; Rust reconstructs the exact checkpoint; a fresh
participant receives and reproduces it via DKG; the outcome is measured and
reported honestly. Improvement is an experimental outcome, not a guaranteed gate.

Original inspiration: https://x.com/rikiyatakehi/status/2117313742891327994 and
https://rikiyat.github.io/blog/weight-space-programming/. This does not claim to
reproduce that paper's Qwen results or demonstrate general capability gains.
