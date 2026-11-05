# Internal vision-network weight edit

This run changes the actual CLIP visual transformer, not just a classifier over cached CLIP features. The selected tensor is `vision_model.encoder.layers.10.mlp.fc2.weight` (768 × 3072, the 11th transformer block). 2,359,291 stored values changed. Other model tensors and the previous four-class classifier remained byte-value identical.

## Result

On 60 previously unused real source photographs: unchanged visual network + fixed previous classifier = 26/60; edited visual network + exactly the same classifier = 31/60. Six errors corrected, one correct answer regressed. This is a modest task-specific exploratory gain, not established general improvement.

The previous 18/60 → 19/60 trial used different test images and a different baseline. These scores must not be directly compared to that trial. Here both sides use the same 60 fresh photos and the same frozen classifier.

## Method and rationale

No gradients or optimizer. The assistant designed and ran a deterministic activation-guided edit script, not a separate autonomous controller. Development errors supply a target margin correction through the frozen readout. A regularized closed-form solve maps internal development MLP activations to a proposed residual-stream correction. Because later blocks and layer normalization are nonlinear, all candidates are measured through the exact modified transformer suffix, and the selected candidate is verified with a full forward pass from images.

The preregistered search tested internal blocks 8, 10, 11 and five strengths per block. The selected candidate was block 10, strength 2. These are choices for this run, configurable through `--layers` and `--gains`, not new application-wide edit restrictions. The fixed classifier is the candidate from the previous real-photo experiment; the original pretrained CLIP network is the starting backbone. Inspect snapshots, causal hypothesis, full search trace and frozen candidate digest are retained.

100 development / 40 selection / 60 new evaluation photos. Selected on the selection set, with development cross-entropy then patch norm as tie breakers. Full evaluation was run only after checkpoint commitment. No post-test tuning.

## Limits

The new evaluation photos come from the same inferred capture sessions whose earlier frames/results were seen in the preceding experiment. They are new images, not new independent print jobs. Capture sessions were inferred from timestamp gaps, not confirmed by source authors. No inferred session crosses the current splits. Labels come from author folders; there is no healthy-print class and no full independent annotation audit. Other CLIP tasks and capabilities were not tested. No DKG round trip was performed for this run.

## Evidence and replay

- `protocol.json`: commitments, rationale, candidate grid, fixed classifier identity
- `inspection-layer-*.json`, `search-trace.json`: inspected weights and measured attempts
- `frozen-candidate.json`: immutable pre-test selection record; `test_evaluated: false` describes that point in time
- `result.json`: final per-image predictions, gains and regressions
- `base-network.safetensors`, `candidate-network.safetensors`: complete actual CLIP checkpoints
- `network-diff.safetensors`: additive internal-weight difference
- `replacement-tensors.safetensors`: exact replacement tensor
- `fixed-head.safetensors`: unchanged classifier, external to CLIP
- `verify.py`, `verification.json`: fresh-process exact patch replay over every model tensor
- `manifest.json`, `SOURCE-README.md`, `source-provenance.json`: exact images, source and license attribution

Run `python3 verify.py` from this directory to verify exact replay. `run.py` requires the pinned cached Transformers model/processor, Python torch/numpy/Pillow/safetensors, and the sibling prior real-photo experiment. It refuses to overwrite a completed result. A new experiment must use a new directory and independent test commitment.
