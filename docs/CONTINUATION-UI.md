# Continue an experiment from the UI

Build `nc`, then serve a participant with an operator-selected Python environment:

```sh
cargo build --locked --bin nc
target/debug/nc --home /absolute/participant serve --port 19500 \
  --controller-python /absolute/venv/bin/python
```

The Python environment needs `requirements-weight-agent.txt`. Codex uses its
existing login; OpenAI uses `OPENAI_API_KEY` from the server environment. The UI
never receives either credential. The requested backend and model are used exactly,
with no fallback. Controller execution uses the existing isolated adapters.

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

All routes require the same bearer token as `/api/state`, have no-store responses,
and remain loopback-only:

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
  "max_edit_elements": 2000000,
  "timeout_seconds": 3600
}
```

Limits: 1–64 rounds, 1–32 probes, minimum probes no greater than maximum,
1–2,000,000 edited values, 60–21,600 seconds, 32 MiB per task input, and 1,000
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
