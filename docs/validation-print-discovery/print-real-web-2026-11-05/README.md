# Real public 3D-print photographs

200 original JPEG photographs downloaded from the FDM-3D-Printing-Defect-Dataset by Hu et al. Source: https://github.com/wengmhu/FDM-3D-Printing-Defect-Dataset . Paper: https://doi.org/10.1007/s00170-024-14452-4 . The source README declares MIT; the complete attribution and license are retained in SOURCE-README.md. Download URL and archive member names are preserved.

50 images each: Cracking, Layer_shifting, Stringing, Warping. No generated images and no `_aug` or `_original` derivative files were selected. No healthy-print class is present. This task classifies defect type; it does not validate healthy-vs-failed detection.

100 development / 40 selection / 60 final evaluation. Seed 17. Capture-session proxies were inferred from timestamp gaps over 10 minutes, and no inferred session crosses splits. Actual print-job IDs were unavailable; correlated frames remain within each split, so 200 photographs are not 200 independent jobs. All 200 files decoded and have different SHA256 hashes. Labels are source-author folders; not independently audited in full. Gallery thumbnails preserve aspect ratio and link to original bytes.

## Actual result

Selected candidate: prototype_blend_0.25. Baseline: 18/60 (30%). Candidate: 19/60 (31.7%). One additional correct image is weak evidence, not a reliable improvement. Selection performance did not transfer well to final evaluation. No post-test tuning was performed. This is a different four-class task from the earlier synthetic run, so their percentages are not directly comparable.

Frozen CLIP image backbone; 2048 classifier values changed by a deterministic closed-form script, no autonomous weight-agent run. The previous synthetic candidate was not evaluated on these differently defined classes. No DKG round trip was run for this real-photo trial. The previous video and X draft still describe the earlier synthetic experiment.

## Files

- gallery.html — all 200 photos, categories and splits
- reviewed-manifest.json / manifest.json — exact archive members, labels, timestamps, splits and hashes
- provenance.json / SOURCE-README.md — provenance and declared license
- protocol.json / selection-trace.json / result.json — fixed method, selection trace and per-image final predictions
- base.safetensors / candidate.safetensors / weight-diff.safetensors — exact checkpoints and changes
- acquire.py / prepare.py / run.py — reproducible acquisition and evaluation; read scripts before rerunning (they write this experiment's files)

The raw dataset source is about 6 GB. HTTP byte ranges downloaded only the selected original files; ZIP CRC and decoded image validity were verified. The incomplete initial full-archive download was removed.
