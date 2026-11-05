# Codex-directed adaptive internal weight discovery

The agent was the current Codex conversation assistant. Python was its measurement and editing tool. No independent controller subprocess or predeclared search grid selected these seven actions. Each next action was written after the assistant read the preceding feedback. The JSONL log records concise experimental rationales, actions, observations and decisions; it is not a raw private reasoning transcript.

## Outcome

Rejected. Probe 07 improved selection from 29/40 to 30/40, but the separately frozen candidate fell from 29/60 to 27/60 on the final 60 new photographs (0 corrections, 2 regressions). The inherited model remains the retained checkpoint. No further tuning used these final outcomes.

## Adaptive sequence

| Attempt | Development | Selection | Agent hypothesis |
|---|---|---|---|
| 1 | 90/100 | 29/40 | Inherited model misclassifies development cracks as warping. Amplifying 64 channels with the strongest positive crack-versus-warp activation contrast may preserve crack evidence through the last blocks. This is a small diagnostic perturbation, chosen after reading the inherited confusion matrices. |
| 2 | 90/100 | 29/40 | Probe 01 moved a crack error from warping to layer shift without fixing it. Rather than amplify existing channels, add a development-derived crack correction at block 9, before inherited block 10. Fit zero desired change for other development cases; use stronger regularization than the prior grid to reduce memorization. |
| 3 | 95/100 | 28/40 | Probe 02 changed no decisions and had weight-delta norm 0.01035. Test the same direction at norm about 0.414, still below the inherited edit norm 1.132, to distinguish insufficient amplitude from a useless direction. Chosen after probe 02 feedback, not a predeclared sweep. |
| 4 | 90/100 | 25/40 | Probe 03 fixed 3 selection cracks but made 4 layer-shift samples false cracks. Keep the crack correction direction while fitting a counter-direction on development layer-shift samples to reduce their crack logit. Use only development labels to fit; same block and strength isolate this protection change. |
| 5 | 95/100 | 25/40 | Probe 04 protection dominated: patch norm increased from 0.414 to 1.476 and crack selection fell to 2/10. Reduce only protection by 10x while preserving the useful crack direction. This tests whether mild class-specific protection can recover the layer-shift regressions without erasing crack evidence. |
| 6 | 100/100 | 28/40 | Both strong and weak crack-only protection failed to improve held-out selection. Abandon the one-class hypothesis: fit a simultaneous residual correction for all remaining development mistakes so layer-shift errors receive their own positive correction. Use block 9 before inherited block 10, moderate gain, and the previously useful ridge fraction. |
| 7 | 100/100 | 30/40 | Probe 06 achieved perfect development classification but selection dropped to 28/40: over-adaptation. Reduce only intervention amplitude to 30%, producing expected norm about 0.384, to test a conservative version. If it cannot improve selection, reject this branch and retain the inherited checkpoint. |

The agent first tested class-selective channel amplification, rejected a confusion shift, tried targeted internal residual correction, increased an underpowered edit, added protection after a measured regression, reduced overstrong protection, abandoned the one-class hypothesis, and finally reduced an overfitting multiclass correction. These decisions were driven by feedback, not scripted in advance.

## What changed

All probes directly modified internal CLIP visual-transformer MLP weight tensors. The inherited checkpoint already contains the previous block-10 edit. The final tested addition changed block 9 (`vision_model.encoder.layers.9.mlp.fc2.weight`). The text network, projection and classifier remained fixed. Closed-form numerical fitting used development activations; no gradients or optimizer. Exact additive replay of every checkpoint tensor passed in a fresh verification process; this proves integrity, not improvement.

## Evaluation limits

100 development and 40 selection photos were reused for adaptive search. Seven selection queries make selection gains exploratory. The final 60 photos were previously unused, with no exact image overlap with either prior trial. Their inferred capture sessions are familiar from earlier evaluated frames, so this is not an independent new-print-job benchmark. Source author labels have not been independently audited in full. Four defect types only; no healthy class. No DKG round trip or app deployment occurred for this candidate. Prior test figures use different images and must not be compared directly.

## Audit and reproduction

- `agent-decisions.jsonl`: sequential assistant choices and final rejection
- `inspection.json`: inherited confusion matrices and tensor inventory
- `action-*.json`, `probe-*/committed-action.json`, `probe-*/feedback.json`: proposals committed before execution, exact measured outcomes
- `lab.py`: tool host with separate inspect/probe/freeze/evaluate commands; it contains no automatic search loop
- `freeze-decision.json`, `frozen/commitment.json`: pre-test agent choice and exact candidate identity
- `evaluation.json`: final per-image predictions
- `network-diff.safetensors`, `frozen/candidate-network.safetensors`: exact rejected candidate for inspection/reproduction
- `verify.py`, `verification.json`: exact replay proof
- `final-decision.json`: rejection and retained parent identity

Use `python3 verify.py` for replay verification. Reproducing probes requires the pinned cached CLIP model/processor and sibling experiment files. Probe directories are append-only in practice: the tool refuses to overwrite an existing probe directory. Read `prepare.py` before rerunning acquisition because it writes this run's manifest. Source: https://github.com/wengmhu/FDM-3D-Printing-Defect-Dataset ; full source attribution remains in the sibling real-photo experiment.
