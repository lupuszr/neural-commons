# Workspace walkthrough · November 6, 2026

[Finished MP4](../workspace-walkthrough.mp4) · 47.92 seconds · 1600 × 1000 · silent.

The video is a real recording of the local app. It previews the new-experiment
form, browses an existing LLM study and its photographs, shows its recorded
collaborators, then opens the separate shared catalogue and copies the configured
workspace graph's native DKG invite.

The setup form is not submitted. The displayed results belong to an existing
recorded experiment. Copying the invite shares the workspace graph; it does not
publish an unshared local experiment or change graph membership. No API responses,
experiment results or screenshots were mocked. The only presentation additions
are a pointer marker and the chapter strip above the app.

The photograph preview comes from the public print-study assets already recorded
in this experiment. The owner's private camera archive is not shown.

## Reproduce the edit

The immutable `source.webm`, chapter/source timing in `timeline.json`, and actual
output timing in `edit.json` are retained here. No narration or music is present.
All retained source footage plays at its original speed. The final encode was
fully decoded without errors and sampled across every second and chapter.

From the repository root, with FFmpeg, ffprobe and Python Pillow installed:

```sh
python3 scripts/render_workspace_video.py docs/media/workspace-walkthrough \
  artifacts/workspace-walkthrough-rebuilt.mp4
```

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

Both browser scripts use Playwright from `.runtime/dkg-source/packages/node-ui`.
The screenshot script also accepts `NC_UI_TOKEN` in the environment when the UI
has token enforcement enabled. Tokens are never stored in the media project.
