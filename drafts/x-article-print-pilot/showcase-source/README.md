# Neural Commons: adaptive discovery showcase

74 seconds, 1920×1080, 30 fps. English on-screen story with an original instrumental underscore; no narration. This is an evidence explainer, not a live screen recording. The final candidate failed (29/60 inherited versus 27/60 candidate) and was rejected.

Run `python3 render.py` with Python 3, Pillow, NumPy and FFmpeg. The renderer uses macOS Arial fonts; change the font paths on other systems. `compose_music.py` regenerates the music if needed. `python3 render.py --stills` exports review frames and the 2000×800 X cover. Source photographs are scaled uniformly and never synthesized or retouched.

Photographs: Hu et al., https://github.com/wengmhu/FDM-3D-Printing-Defect-Dataset. The dataset README declares MIT and is retained in assets/SOURCE-README.md. These are dataset labels, not independently reviewed labels. Four defects, no healthy-print class. Final images were new frames from known sessions, not independent new print jobs.

The DKG section is explicitly an architecture view referencing an earlier, separate local two-node proof. The adaptive real-photo trial was local only.

The exact experiment evidence lives in docs/validation-print-discovery/ in the repository. The asset manifest records photograph hashes; timeline.json records timings. The video numbers are asserted against source evidence by the renderer.

Validation: full FFmpeg decode passed; encoded frames at all story beats were visually inspected. Audio measured -22 LUFS / -13.9 dBFS true peak. Full normal-speed audiovisual review was not performed. See validation.json.
