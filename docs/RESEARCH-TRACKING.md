# Track conversation-led research in the app

Use the **same participant home as the running UI**. Research records live in its
`journal.sqlite`; evidence files are copied into its content-addressed artifact
store. They appear alongside existing evaluated experiments without manufacturing
an `EvaluationSpec`, a passing report, or a DKG publication.

Register each experiment once, then run every probe through `nc research run`.
The start event is committed before the command is launched. Failed registration
prevents execution. Successful execution means **Awaiting review**, not accepted.
Append the measured result and the agent's decision after reading the feedback.

```python
import sys
sys.path.insert(0, 'scripts')
from research_tracker import Tracker

t = Tracker('/absolute/participant', 'my-experiment')
t.record('experiment', {
    'name': 'Visible print failures',
    'model': 'HuggingFaceTB/SmolVLM-500M-Instruct',
    'objective': 'Improve failure detection while preserving ordinary language.',
    'scope': 'Preliminary source labels; correlated camera frames.',
}, evidence=['/absolute/protocol.json'])

t.run('b-probe-01', {
    'label': 'B · first probe', 'kind': 'probe', 'participant': 'B',
    'hypothesis': 'A smaller internal edit may preserve earlier web behavior.',
    'parent_sha256': 'the-verified-parent-file-hash',
    'operation': {'action_file': '/absolute/action.json'},
}, ['python3', '/absolute/probe.py', '/absolute/action.json'],
    result='/absolute/new-output/feedback.json',
    evidence=['/absolute/action.json', '/absolute/probe.py'])

t.feedback('b-probe-01', '/absolute/new-output/feedback.json',
           'Selection improves; final evaluation remains unopened.')
t.record('decision', {
    'verdict': 'not_selected',
    'reason': 'The web regression violates the recorded acceptance requirement.',
}, round_id='b-probe-01')
```

Choose the actual hypothesis and operation from measured feedback. The tracker
does not choose edits or impose model/layer/edit-size restrictions. The Python
helper's nested metric normalizer supports `n`/`correct` feedback; other tools can
append explicit `measurements` without adopting this format.

## CLI and event contract

```sh
nc --home /absolute/participant research record /absolute/event.json
nc --home /absolute/participant research run /absolute/round.json \
  --result /absolute/new-feedback.json -- python3 /absolute/probe.py
nc --home /absolute/participant research list
```

An event contains `id`, `experiment`, `kind`, `data`, optional `round`,
`historical`, `occurred_at` (Unix seconds), and `attachments`:

```json
{
  "id": "probe-1-feedback",
  "experiment": "my-experiment",
  "round": "b-probe-01",
  "kind": "result",
  "data": {
    "status": "completed",
    "summary": "Candidate measured on selection, not the final set.",
    "measurements": [{
      "label": "Camera accuracy", "split": "selection",
      "parent_correct": 21, "correct": 26, "total": 40
    }]
  },
  "attachments": [{"label": "Feedback", "path": "/absolute/feedback.json"}]
}
```

Event kinds are `experiment`, `round`, `result`, `decision`, `status`, and `note`.
Experiment definitions require `name`, `model`, and `objective`. Round definitions
require `label`, `kind`, and `hypothesis`. Results require `status` and `summary`;
decisions require `verdict` and `reason`. Metric split roles are `development`,
`selection`, `final`, `regression`, or `diagnostic`. Counts must be valid for the
stated denominator. Keep different cohorts as separate metrics.

Use a `status` event to set experiment status (`in_progress`, `completed`,
`rejected`, `archived`) and its summary. Round result states are `completed`,
`awaiting_review`, `failed`, or `interrupted`. Decisions are `accepted`, `rejected`,
`not_selected`, `not_promoted`, or `inconclusive`; preserve their scope in the reason.
Append corrections as new events; previous records and attachments remain visible.

IDs allow ASCII letters, digits, hyphens and underscores, up to 128 characters.
Repeating an event ID with identical content is idempotent; different content is
rejected. Experiment/round definitions cannot be silently replaced. Attachments
accept either an absolute local `path` or an existing `artifact` SHA-256, up to
16 MiB each. Large model files remain in the normal checkpoint registry; record
their verified identities and verification reports here. Source attachments are
copied, so subsequent changes to the original file cannot rewrite old evidence.

The managed command holds an execution lease inherited by its child. Restarting
the web server does not interrupt it. Loss of the worker without a recorded result
is displayed as **Interrupted**, and the command is never automatically retried.
Use a new round ID for an explicit retry. `--result` must name a fresh output path;
a stale, missing or invalid result cannot masquerade as a successful measurement.
Command logs and feedback are preserved; a decision still requires agent review.

## UI and historical recovery

`GET /api/research` uses the normal participant authentication/origin policy.
The UI polls it every five seconds while visible. Active research appears first;
the overview distinguishes experiment activity from an executing numerical worker.
Expand a round to inspect its hypothesis, measurements, operation, weight hashes,
decision and copied evidence. The Evidence tab includes the complete event history.
An experiment link uses `/#experiment-id`; reloading retains that selection.

The **Collaborators** tab reads an optional `collaboration` object from the
experiment definition or an experiment-level `note`. Include `context_graph`,
`summary`, and `participants` (`{name, address, roles}` objects, with an EVM agent
address and an array of role labels). Attach the DKG handoff evidence supporting
those identities. These are recorded contributors, not a live membership or online
status claim. Run labels such as A/B do not establish participant identities.
The workspace's **Shared experiments** page is separate and reports the configured
graph's participants and shared proposals; it is never nested under an experiment.

The **Description** tab shows the goal, model, method, dataset, evaluation,
limitations and sources. Add a `description` object to the experiment definition
or an experiment-level `note`; later notes update the displayed fields while
preserving earlier evidence. Supported fields are `summary`, `method`, `dataset`,
`evaluation`, `limitations` (strings), and `sources` (`{label, url}` objects).

The **Assets** tab collects attached files across the experiment and its rounds,
groups duplicates by content identity, and links the experiment's model checkpoints.
It offers search, type/split filters, paginated photo previews and original-file
downloads. Images and downloads use the authenticated artifact endpoint; the
browser never reads arbitrary local paths or executes attached HTML.

The overview displays completed training epochs recorded as
`data.training_progress` on round events. Include integer `epoch` and `epochs`,
and a finite, nonnegative `class_loss`; `box_loss` and `dfl_loss` are optional.
Only measured loss series are plotted. For a custom objective, include
`loss_definition` so a partial dog-head fit is not presented as a full detector
training loss. A completed or failed round keeps its progress without claiming
that a training worker is still running. This display does not replace the
separate selection and final evaluation records.
To invalidate a spurious progress event without changing history, append a note
with `training_progress: {epoch: N, valid: false}`. The plot removes that epoch;
the original event and correction remain in Evidence.
An optional finite, nonnegative `anchor_penalty` plots the measured weighted
regularization objective at epoch end as a separate series. It is not added to
the displayed supervised Class/Box averages, whose aggregation remains unchanged.

An optional `assets` array on an event enriches that event's attachments. Match
each entry's `artifact` SHA-256 to an attachment and supply `label`, `filename`,
`kind` (`image`), `split`, `caption`, `target_label`, and optionally `source_url`.
Files without these hints still appear as ordinary attachments.

For a local photo manifest with `rows` containing `image` and `sha256`, use:

```sh
python3 scripts/attach_research_assets.py --home /absolute/participant \
  --experiment my-experiment --description /absolute/description.json \
  --manifest /absolute/manifest.json
```

This verifies every image against its committed hash, copies files into the
artifact store and appends bounded, idempotent notes. It does not run a research
round, modify a data split or publish files to DKG.

To connect an actual model to a round, register it with the normal `nc register`
command, then include `checkpoints` in that round's result: a list of
`{label, checkpoint, sha256, parent_checkpoint?}` objects. The checkpoint is the
verified manifest ID, and `sha256` identifies the weights file. The overview opens
the existing tensor inspector and compares against `parent_checkpoint` when set.
The Model versions list refreshes with research updates. BF16/F16/F32 conversions
are compared by numeric value; an exact cast does not count as a changed weight.

`scripts/import_research_history.py --home /absolute/participant` recovers the
existing November 4–5 print-study artifacts, including unsuccessful attempts and
earlier non-LLM pilots. Imported rounds explicitly identify historical provenance.
Original evidence times and the journal's import times are distinct. This importer
does not execute experiments, change labels, publish to DKG, or turn exploratory
scores into final results. New experiments must use managed tracking from the start.

Validation: `cargo test -p neural-commons` and
`node scripts/research_ui_check.cjs` cover append-only history, immutable evidence,
registration before execution, failures, duplicate prevention, server restart,
automatic UI updates, split labels, reload/deep links, mobile layout and API origins.
`node scripts/collaboration_ui_check.cjs` and `node scripts/share_api_check.cjs`
cover workspace navigation, experiment and graph scope, contributor deduplication,
public graph semantics, access checks and unavailable membership.
`node scripts/training_ui_check.cjs` checks epoch validation, corrections, measured
loss series, accessible progress and idle/failed training states without a browser.
