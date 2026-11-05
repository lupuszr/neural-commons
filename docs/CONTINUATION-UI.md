# Create and continue experiments from the UI

Build `nc`, then serve a participant with an operator-selected Python environment:

```sh
cargo build --locked --bin nc
target/debug/nc --home /absolute/participant serve --port 19500 \
  --controller-python /absolute/venv/bin/python
```

The UI connects automatically by default (`require_token: false`). Set
`"require_token": true` in the participant's `config.json` and restart to show the
token form, or use `nc --home /absolute/participant serve --require-token`.
`GET /api/ui-config` returns the effective mode, never the token. In automatic
mode the server does not read the UI token file. The listener remains loopback-only
and rejects foreign browser origins and non-loopback Host values for API access.

The Python environment needs `requirements-weight-agent.txt`. Codex uses its
existing login; OpenAI uses `OPENAI_API_KEY` from the server environment. The UI
never receives either credential. The requested backend and model are used exactly,
with no fallback. Controller execution uses the existing isolated adapters.

## Invite collaborators through DKG

Click **Invite collaborator** in the workspace toolbar. **Share context graph**
shows the configured graph and its native DKG invite code: the graph ID followed
by the curator node’s libp2p peer ID on a second line. Copy the code and send it to
your collaborator; they paste it into **Join project** in their own DKG node.
Both nodes must be running and mutually reachable on the same DKG network.

The graph’s existing DKG access and contribution policies apply. If a signed join
request needs approval, use **Open DKG** and review it in the graph’s sharing
panel. The invite shares the entire context graph, including its shared records;
it does not expose this local UI or send its access token. It does not publish
unshared local experiments. The app creates no separate collaborator accounts,
permissions, public links or membership bypass.

`GET /api/context-graph/share` uses the existing UI access policy and reads only
the configured local DKG node. It checks graph read access and the curator-only
join-request route before combining the graph ID with the node identity. If the
node is unavailable or cannot manage this graph, copying is disabled and an
explicit unavailable message is shown. No invitation text is generated from
cached identities. DKG credentials remain server-side.

## Browse shared experiments

Open **Shared experiments** to query this participant's configured DKG context
graph. The catalogue lists shared `PatchProposal` records in pages of 20. Each
record's content hash, graph and authenticated author placement are verified
before it becomes actionable. Discovery does not download model files or start
an evaluator. A disconnected or denied graph is shown as unavailable, not as an
empty successful result. Refresh reads the node's currently synchronized data.

**Download model & evidence** uses native DKG artifact transfer and verifies the
bundle. Base and candidate checkpoints become available in **Model versions**,
and the proposal appears in the local experiment list without an evaluation.
**Open experiment** shows its evidence. **Reproduce & share result** runs the
locally configured evaluator against the exact specification, then publishes the
evaluation and review back to the graph. The button explicitly includes sharing;
downloading alone never runs or publishes an evaluation. The evaluator build and
dependencies must match the specification. Interrupted/unavailable jobs expose an
explicit retry; completed computations are reused when publication is retried.

Eligible downloaded proposals with a passing report and weight-agent session
also expose **Continue this experiment**, using the existing continuation form.
This still requires fresh prepared task data and a controller configured by the
local user. A graph invitation alone does not initialize Neural Commons or install
an evaluator on the collaborator's machine; initialize their participant against
their own DKG node and the same graph as described in [V1](V1.md).

`GET /api/shared-experiments?offset=0` uses the existing UI access policy and
returns verified proposal envelopes, local download receipts and `next_offset`.
It does not fetch other participants' credentials or permit arbitrary DKG URLs.
The UI uses the existing serialized `/api/actions` operations for download and
reproduction; large transfers can take minutes. If the browser loses an operation
response, refresh local records before retrying. A successful reproduction with
an unsuccessful DKG publication is not labelled successfully shared.

Validation on 2026-11-04 used freshly fetched DKG canary
`feb7f4f77bea104e9941d3fc8eaabe9759f5070f` with the documented opaque-source patch.
The [public two-node run](validation-shared-ui/public-two-node.json) passed native
invite/subscription, real discovery, browser-driven download without evaluation,
independent reproduction, publication of evaluation/review, and readback by the
first participant. It used a labelled synthetic model fixture, separate local
node processes/stores and a disposable local EVM. It is not a new LLM-controller
experiment or a remote-machine/WAN test. All test services were stopped.

The [private graph run](validation-shared-ui/private-partial.json) verified signed
join/approval, discovery, download and local evaluation, but did not complete
encrypted result publication. The DKG failure occurred in recipient resolution /
`encodeWorkspaceGossipPayload`; follow-up private runs also encountered
post-approval read-authority issues. No private sharing success is claimed.

Reproduce these checks with `python3 scripts/shared_experiments_check.py --public`
or omit `--public` to exercise the private signed-join path. The script fetches
canary immediately before validation and refuses a stale build. The controlled
API fixture (`node scripts/share_api_check.cjs`), catalogue integrity unit tests,
and browser regressions (`node scripts/ui_check.cjs PARTICIPANT_HOME --local`)
cover authentication, pagination, tampered records and unavailable states
separately from real transport evidence.

## Start a new experiment

Click **+ New experiment** in the workspace toolbar. Enter a name, select an
imported starting model, and choose a prepared task folder on the server machine.
Choose **Editable weights**: the whole model (default), or specific tensors from
the imported model. Optionally enter your goal and additional instructions, then select the controller backend,
model and execution limits and click **Start experiment**. No parent proposal or
passing evaluation is required. **Import another model** opens a dedicated local-folder importer. Paste an absolute
folder path containing `model.safetensors`, `config.json`, `tokenizer.json` and
`tokenizer_config.json`; configuration and tokenizer files are detected and bound
to the checkpoint automatically. If `special_tokens_map.json` is absent, its
mapping is derived from the special-token fields in `tokenizer_config.json`.
Importing copies artifacts into the participant store without changing source
files or contacting DKG. Missing files and unsupported sharded models produce
specific errors. After import, the experiment form retains its fields and selects
the new model. Cancelling returns to the form with the previous selection.

The same importer is available in **Model versions → Import checkpoint**.
Advanced mapping-based registration remains in **Checkpoint operations**.
CLI equivalent: `nc --home /absolute/participant import-model /absolute/model-folder`.

The current weight-agent adapter requires a single-file Safetensors checkpoint
with `model_config`, `tokenizer`, `tokenizer_config` and `special_tokens` inference
artifacts. Unsupported models are omitted from the picker and rejected by the API.
The task folder has the same files listed below; it must already contain disjoint
development, selection and held-out splits. The form does not download datasets,
create splits or prepare task configurations. The [AG News preparation workflow](AGNEWS-WORKFLOW.md)
is one supported example. A fresh experiment can reuse an existing task for a
new comparison; it does not claim those examples are fresh relative to prior runs.

The backend verifies the registered checkpoint, binds task hashes on admission,
and snapshots model files and inputs before controller execution. For both fresh
experiments and continuations, the user's goal, instructions and weight selection
replace the task file's agent objective, instructions and edit scope in the copied
configuration. A blank goal uses the visible default: improve task accuracy, with
lower label NLL as a secondary goal. Whole model removes task-authored weight
restrictions; selected tensors become enforced regions covering those tensors.
The source task and its evaluation/acceptance rules remain unchanged. These user
choices are saved in the request and hashed controller input. Free-text instructions
guide the agent; tensor scope and numeric execution budgets are enforced. The experiment name travels with the source evidence.
Runs appear immediately under **Controller runs**, with the same cancellation,
restart recovery, resume and candidate-import retry as continuations. Choose
**Evaluate candidate** when the run completes; the evaluated experiment appears
in the sidebar with its name. Evaluation and publication remain explicit actions.

`POST /api/experiments` takes the same limits, backend, model, checkpoint and
`task_directory` as a continuation, plus a required `name` (1–120 UTF-8 bytes) and
optional `objective` and `instructions` (each 1–4000 bytes). Both endpoints require
`weight_scope`: `{"mode":"all"}` or `{"mode":"selected","tensors":["exact.tensor.name"]}`.
Omit `proposal` and `report`. The endpoint
uses the configured UI access mode. Run status and controls use the existing
`/api/continuations` routes; new runs have `kind: "experiment"`. Request IDs remain
idempotent across retries and server restarts. A running experiment and a
continuation share the same execution lease.

## Folder and controller selection

**Browse…** opens a folder chooser for task folders and model imports. It offers
Workspace, Downloads and Home shortcuts, parent navigation, folder filtering and a
hidden-folder toggle. Required filenames are shown with presence checks; **Use
this folder** is enabled only when they are present. File contents, split overlap,
model compatibility and policy semantics are still checked during import/run
preparation. Browsing does not upload files or start a controller.

The **Controller model** dropdown follows the selected backend. Codex choices are
read from `CODEX_HOME/models_cache.json` (or `~/.codex/models_cache.json`), excluding
hidden catalog entries. Refresh rereads that local cache; open Codex to refresh
its upstream catalog. API choices come from the account's
[OpenAI model list](https://developers.openai.com/api/reference/resources/models/methods/list)
using the server's `OPENAI_API_KEY`. The credential is never returned to the UI.
Obvious non-text model families are filtered; the API catalog does not guarantee
Responses/structured-output support for every listed ID. **Custom model…** allows
an explicit ID if the catalog is missing or the desired model is not listed.
The selected ID is passed through unchanged; there is no model fallback.

`GET /api/folders?kind=task|model&path=...&hidden=false` and
`GET /api/controller-models?backend=codex|openai` use the same access policy as
other participant APIs. Catalog calls do not perform inference.

## Checkpoint visualization

Checkpoint details show an interactive map above the tensor table. Counts and
relative sizes come from the checkpoint's saved tensor shapes. Groups use tensor
names (embeddings, numbered layers/blocks, and other tensors); this is a storage
map, not a computed execution graph or an activation/weight-value heatmap.
Click a group to filter the table, or **Show all** to restore every tensor.

## Continue an existing experiment

Choose an evaluation and **Continue from candidate**. Eligible parents have a
weight-agent session, an authenticated proposal in this participant's journal,
and a passing evaluation report for the exact proposal and candidate checkpoint.
A later policy reassessment stored only in project documentation does not replace
that report. Unsupported checkpoints or inconsistent parent evidence fail before
any controller call.

Provide an absolute directory containing the next task's `config.json`,
`development.json`, `selection.json`, `heldout.json`, `policy.json` and
`source.json`; include `guard.json` and `guard-config.json` when configured.
Use the existing task preparation workflows to create these inputs. The service
builds the inherited model and handoff from the participant's verified local
artifacts; no model download or DKG fetch is needed for that step. The importer
requires an active configured DKG node to resolve the new patch's author during
import. The worker checks node identity before calling the controller. The task config
must include the existing selection policy. Development, selection and held-out
samples must be mutually disjoint and exclude exact texts from the immediately
prior task. This check does not claim exclusion from every ancestor or pretraining.

Choose the backend, controller model and budgets, then **Start controller**.
Admission binds the task input hashes; the worker rejects changes made before
snapshotting. All subsequent phases use the frozen snapshot. The workflow is:

1. Verify the recorded parent and reconstruct its patch with Rust; prepare the
   exact numerical diff and inherited inference files.
2. Run the controller against development data within the requested limits.
3. Select among frozen proposals using the reserved selection split and policy.
4. Import the frozen candidate, reconstruct its patch and prepare an evaluation
   specification in the artifact store.

The final set is hashed and checked for split overlap outside controller input;
no held-out inference runs during the search job. In **Controller runs**, choose
**Evaluate candidate** and review the populated operation before running it.
Evaluation then appears in the regular experiment list. Sharing/reproduction
remain separate existing operations. A completed controller job means a candidate
is ready, not that it passes evaluation or has been published.

## Status and recovery

Runs live under `PARTICIPANT/continuations/UUID/`: the immutable request,
input snapshots, state, worker log, controller transcript, selection report and
frozen result remain available. Browser refresh and server restart do not restart
controllers. Worker and subprocesses inherit an OS execution lease; at most one
controller or UI participant operation may hold it. API keys are not written into
run requests or browser state. Worker logs stay local and are not served by an API.

**Cancel run** writes a durable intent. The supervisor stops the child process
group and waits for cleanup before releasing its lease. The time limit uses a
wall-clock deadline even for a silent controller. If the supervisor dies, the work
child retains the lease; after it exits, the next status read recovers a recorded
result or marks the run interrupted. A lease held by an orphaned descendant blocks
new work rather than pretending cleanup finished.

**Resume search** is available only when a transcript exists and the controller
has not finalized or begun selection. It retains the original request, snapshots,
controller, budgets and attempts; the existing transcript/commitment checks apply.
The wall-clock timeout is per resume attempt. **Retry candidate import** reuses an
already selected frozen session if importing it failed (for example, the DKG node
became unavailable); it never calls the controller or selector again. Preparation
failures and incomplete selection retain evidence but cannot resume through this API.
A new request ID starts new work; the same ID and request returns the existing run.

## API

All controller routes use the same access mode as `/api/state`, have no-store
responses, and remain loopback-only. With `require_token: true`, the bearer token
is mandatory; the default mode accepts local requests without it:

- `GET /api/continuations`: up to 100 newest runs with status and resumability.
- `POST /api/continuations`: validate and admit a run, returning its durable ID.
- `POST /api/continuations/{id}/cancel`: request cancellation idempotently.
- `POST /api/continuations/{id}/resume`: resume eligible interrupted search.

The start body is strict JSON with no extra fields:

```json
{
  "id": "a402b382-07d1-4f67-975f-c637a1d44181",
  "checkpoint": "<parent candidate SHA256 manifest ID>",
  "proposal": "<authenticated parent proposal ID>",
  "report": "<recorded passing report artifact ID>",
  "task_directory": "/absolute/path/to/new-task",
  "backend": "codex",
  "controller_model": "<model available to your account>",
  "max_rounds": 16,
  "max_probes": 8,
  "min_probes": 1,
  "weight_scope": {"mode": "all"},
  "max_edit_elements": null,
  "timeout_seconds": 3600
}
```

Limits: 1–64 rounds, 1–32 probes, minimum probes no greater than maximum,
an optional positive integer budget for edited values (`null` means all stored model
values; no fixed two-million cap), 60–21,600 seconds, 32 MiB per task input, and 1,000
retained runs per participant. Checkpoint byte limits remain unchanged. Request
paths identify data only; script and Python execution are configured by the
server operator, never by the HTTP request. Different requests reusing an ID or
requests while another worker holds the lease fail with a conflict.

## Local validation

```sh
cargo test --locked -p neural-commons
python3 -m unittest discover -s scripts -p 'test_weight_*.py'
python3 -m unittest discover -s scripts -p 'test_continuation_job.py'
node scripts/continuation_api_check.cjs /absolute/participant-with-passing-proposal
node scripts/ui_check.cjs /absolute/completed-participant
```

The HTTP check uses a copied participant and an inert worker to verify admission,
idempotency, restart and cancellation. Lifecycle unit tests exercise real process
termination and mocked controller boundaries. These checks never call a paid model
and do not constitute a live controller-run validation.

### Compare actual weight changes

When checkpoint details belong to a recorded experiment, the UI compares that
experiment's base and candidate checkpoint bytes. Orange groups contain changes;
gray groups are unchanged. The summary counts actual changed values and tensors,
not the size of replacement regions in a patch. **Changed tensors only** starts
selected. Click a group to filter the tensor list; **Show all** resets the group.

**Before → after** lists the exact stored values, signed difference, tensor name,
flat index and multidimensional coordinate. Filter by changed tensor and page
through the result (100 values per page). The backend verifies artifact hashes and
compatible layouts, then streams the comparison with bounded buffers. F32, F16
and BF16 changes are supported, including sharded checkpoints with matching layouts.
Changes use bitwise comparison of stored values, so signed zero or changed NaN
representations count as changes. Non-finite values are labelled explicitly.

`GET /api/checkpoint-diff?base=ID&candidate=ID&tensor=NAME&offset=0&limit=100`
uses the configured UI access policy. `tensor` is optional; the maximum page size
is 200. No weights are edited and no inference is run. Checkpoints with no recorded
experiment retain the structural view; missing or incompatible comparisons show
an error instead of a zero-change result.
