# Workspace walkthrough · November 6, 2026

[Finished MP4](../workspace-walkthrough.mp4) · 71.16 seconds · 1920 × 1080 · silent.

The video starts with participant A: preview the new-experiment form, browse an
existing LLM study and its photographs, inspect its recorded collaborators, then
open the shared catalogue and copy the workspace graph's native DKG invite.

At 38.96 seconds, the screen splits and participant B appears. B downloads a
shared SmolLM2 model and its evidence while A browses the experiment's evidence
and collaborators. Both workspaces remain visible through the end, including a
side-by-side inspection of the identical candidate checkpoint and weight diff.
The two panes retain their original playback speed and relative capture timing.

This uses two real DKG nodes on one Mac, with separate Neural Commons workspaces
and identities, both operated by the same assistant for the demonstration. B's
fresh workspace goes from **0 records / 0 checkpoints** to **1 record / 2
checkpoints** through the UI's verified download. No controller job is started.
The source timings, proposal and checkpoint identities, and before/after counts
are in [`split/split-timeline.json`](split/split-timeline.json).

The setup form is not submitted. The displayed results belong to existing
recorded experiments. The photograph study is separate from the shared SmolLM2
experiment. B was already subscribed to this public graph; the recorded action
adds the model and evidence to B's empty local workspace. Copying the invite does
not publish an unshared local experiment or change graph membership. B has no
new local evaluation, as its final overview shows.

No API responses, experiment results or screenshots were mocked. Presentation
additions are a pointer marker in the original tour, chapter and participant
labels, and a short panel reveal at the split. Each split pane is the actual
940 × 900 responsive app view, without horizontal compression.

The photograph preview comes from the public print-study assets already recorded
in this experiment. The owner's private camera archive is not shown.

## Reproduce the edit

The original `source.webm`, `timeline.json` and single-participant `edit.json` are
retained. The revised video uses the first six original chapters, followed by
`split/participant-a.webm` and `split/participant-b.webm`.
[`split/edit.json`](split/edit.json) is the current output timeline. The renderer
aligns the split to the actual encoded viewport resize, before the capture
script's settled marker, to exclude recording-canvas padding. No narration or
music is present. The final encode was fully decoded and visually sampled across
every second, including the transition and both panes.

From the repository root, with FFmpeg, ffprobe, Python Pillow, NumPy and OpenCV
installed:

```sh
python3 scripts/render_shared_split.py docs/media/workspace-walkthrough \
  artifacts/workspace-walkthrough-rebuilt.mp4
```

To capture the two-participant portion again, use two running token-free local
workspaces with different DKG identities subscribed to the same graph. A must
already have the selected shared proposal; B must have an empty local journal
and checkpoint store. Create a local session JSON with `participant_a_url` and
`url` (B's workspace URL), then run:

```sh
node scripts/record_shared_split.cjs /path/to/session.json PROPOSAL_ID \
  artifacts/new-workspace-walkthrough/split
```

This performs a real model/evidence download into B. It verifies the two
identities, matching graph, base and candidate checkpoint IDs, absence of new
jobs, and the sole mutating API request (`fetch`). It never prints invite codes
or DKG credentials. Capture into a new directory to preserve existing sources.

To capture a new walkthrough from a running token-free local app, provide a real
experiment and an existing prepared task directory. The script expects an
imported SmolLM2 base for the news-task setup and a research experiment with a
recorded `final-evaluation` round, photo assets and collaborators:

```sh
node scripts/record_workspace.cjs http://127.0.0.1:19500 EXPERIMENT_ID \
  /absolute/path/to/prepared-task artifacts/new-workspace-walkthrough
```

To refresh the main README screenshots, use:

```sh
node scripts/capture_workspace.cjs http://127.0.0.1:19500 EXPERIMENT_ID
```

The browser scripts use Playwright from `.runtime/dkg-source/packages/node-ui`.
The screenshot script also accepts `NC_UI_TOKEN` in the environment when the UI
has token enforcement enabled. Tokens are never stored in the media project.
