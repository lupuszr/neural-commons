# Real-photo discovery evidence

These snapshots preserve the measured outcomes and failed proposals. Large photographs, full checkpoints and tensor payloads remain under the local ignored `artifacts/` directory. This folder is an audit snapshot, not a self-contained runnable experiment bundle. Reproduction scripts retain their original sibling-directory assumptions; restore the corresponding artifact layout and pinned model cache before running.

| Run | Measured comparison | Interpretation |
|---|---|---|
| Real-photo classifier edit | 18/60 → 19/60 | Different classifier on frozen CLIP features; weak gain. |
| Internal visual-network edit | 26/60 → 31/60 | Same classifier, internal block-10 tensor changed; exploratory gain. |
| Adaptive Codex continuation | 29/60 → 27/60 | Seven feedback-driven attempts; final candidate rejected. |

Each row uses its own final image set. Do not treat rows as a common benchmark trajectory. New frames came from previously observed capture sessions; none establishes performance on independent new print jobs. Four defect categories only, no healthy-print class. No DKG round trip was run for these real-photo trials. Earlier two-node DKG demonstrations are separate evidence.

The current conversation assistant was the agent in the adaptive run. Python was its tool. The decision ledger records brief hypotheses, measured feedback and acceptance decisions, not a private reasoning transcript.

Source photographs: [Hu et al., FDM-3D-Printing-Defect-Dataset](https://github.com/wengmhu/FDM-3D-Printing-Defect-Dataset). Source attribution is retained in the run snapshots.
