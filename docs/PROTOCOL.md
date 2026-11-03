# Original local-delivery contracts

Historical first-delivery protocol. See [V1.md](V1.md) for the current file-backed engine, DKG artifact transport and evaluator process contract.

All hashes are lowercase SHA-256 hex. Each JSON artifact's identity hashes its exact compact serialized bytes. A patch's own digest is its artifact identity (it is not included recursively inside its own manifest). Rust structs define ordered fields; extensible maps use sorted keys. Unknown fields are rejected at typed input boundaries. The local SQLite job UUID, content digest and DKG KA identity are separate identifiers.

## Generic tensors and artifacts

Safetensors 0.8.0 validates serialization. Import inventories arbitrary names/ranks and preserves all dtypes recognized by that library; **editing supports F32 only**. Unsupported edit dtypes fail explicitly. Quantized mutation is not implemented. Checkpoint manifests bind serialized checkpoint bytes, inventory, and named inference artifacts. The core does not know MLP names, layers, metrics or architecture.

Region replacements use `tensor`, exact `dtype` and `shape`, a zero-based row-major flat element `offset`, positive `count`, and the digest of little-endian F32 payload bytes. A contiguous interval may cross row boundaries; it is not an implicit multidimensional rectangle. Replacement is the only operation. Coordinates and payloads must fit, replacement values must be finite, and overlapping intervals are rejected. Output preserves the original file header/metadata/order and every untargeted byte. The expected result digest is checked before any output is made available. Parents are immutable. Patch composition is never automatic.

Limits: 64 MiB per artifact/checkpoint, 4,096 tensors, 32 dimensions, 1,024 bytes per tensor name, 1,024 patch operations. Bundles contain at most 128 references and at most 128 MiB downloaded bytes in total. Artifact paths are derived only from validated content IDs. Atomic no-clobber publication fsyncs the file and parent directory; every read verifies its hash. Participant directories are private to the local user and must not be shared with untrusted filesystem writers.

## Evaluation

`EvaluationSpec` binds base and candidate checkpoint manifests, patch lineage, dataset, inference config, evaluator identity/version, executable digest, backend identity, seed, metric, resource bounds and acceptance policy digest. Candidate generation is independently checked by applying the patch. Both checkpoint manifests must bind the same inference artifacts and the selected config. Evaluators cannot choose executable commands from a proposal: this build dispatches only its compiled `nc/scalar-mlp-cpu/v1` adapter.

The reference adapter is a native Rust dense/ReLU/dense MLP with explicit config-selected tensor names. It intentionally has no training or model-download dependency. This is a small replacement for the proposed Candle dependency, keeping the evaluator extension boundary independent of the tensor engine. Dimensions are limited to 64, dataset size to 4,096 samples and runtime to 30 seconds. The parent also enforces a wall-clock deadline on the fresh worker process. Seed zero and scalar F32 CPU execution are explicit; the environment records OS/architecture. Executable identity makes a new build a new evaluation input.

The fixture is a deliberately damaged identity function. Development inputs and held-out inputs are separate artifacts. Before evaluation, the fixture fixes maximum candidate MSE, minimum improvement and tolerance. A repair restores the known function; a regression reverses its output. Neither is evidence of discovering a novel capability. Reports separate `passed`, `failed`, `interrupted` and `unavailable`, retain predictions and both measured scores, and bind the exact specification. Byte digests establish artifact integrity; metric tolerance governs numerical acceptance.

## DKG and artifact transfer

The client uses authenticated `/api/agent/identity`, `/api/knowledge-assets` (explicit `finalize`, `alsoShareSwm`, `alsoPublishVm:false`) and graph-scoped `/api/query`. Names are deterministic `nc-<record digest>` for same-author reconciliation. A successful HTTP response with a partial share status is not success. Uncertain writes become `unknown` and must be read back before retry.

Records use a versioned RDF namespace `urn:neural-commons:v1:` and types ModelVersion, Hypothesis, PatchProposal, Evaluation, Review and DerivedVersion. Binary values live in the artifact store; DKG holds references and semantic evidence. Record identity binds its author, graph, content bundle, configured artifact origin and lineage reference. Claims about behavior remain attributed claims.

The current DKG RFC-64 receiver applies accepted author-catalog rows into per-KA graphs under `did:dkg:context-graph:<cg>/_shared_memory/<author>/<number>`. A graph-scoped `GRAPH ?g` query binds the record to that authenticated placement. Claimed author, graph and exact content hash must agree. A remote participant's local KA alias is not relied on for provenance. This trust boundary relies on the authenticated, pinned local DKG daemon's verified catalogue projection; this Rust client does not reimplement DKG signature verification.

DKG's query route deliberately hides unauthorized graphs as empty query results. The client therefore calls the explicit graph read-authority gate at `GET /api/context-graph/{id}/participants` before reading, and again when a query is empty. A 403 remains an explicit access-denied error; a 503 remains unavailable. This check does not freeze DKG policy across requests: a subsequent revocation can still interrupt a fetch or reproduction.

Downloads are permitted only from an exact operator-configured loopback origin, with a separate artifact bearer token. Proposals cannot redirect the downloader to a new origin. Redirects and proxies are disabled; requests have connect and total deadlines, size limits and hash verification. B does not open A's artifact directory. Both participants belong to the same local OS user; this is process/store separation, not OS sandboxing or independent organizational trust.

## Work and recovery

Each participant has a bounded synchronous worker queue of capacity one, protected by an exclusive filesystem lock and a SQLite WAL journal with FULL synchronization. Stable UUID job IDs and exact specification identities are persisted before execution. Another request while the worker is busy gets an explicit error. On reopening the journal, unfinished computation becomes `interrupted`, and unfinished publication becomes `unknown`.

Completed reports are reused without rerunning evaluation. Interrupted/unavailable jobs require explicit `--retry`. Publication records are separate from jobs, so sharing can retry without recomputation. Content-addressed KA names plus query reconciliation prevent duplicate publication after an uncertain response. An explicit `shared` state is local sharing success; the second participant's `remote-dkg-readback` record is separate evidence of reception.

SQLite triggers retain append-only job and publication transition history in the same transaction as each state change. Retry preserves earlier report references in this history. The worker holds a separate execution lock, so a child surviving a terminated supervisor cannot overlap a retry. Reports include the worker process ID as local execution evidence, not as a cryptographic identity. The UI exposes the most recent 100 transitions; older transitions remain in SQLite.

The UI reads local records through an authenticated API, labels synthetic fixtures, and distinguishes local shared records from remote readback. It does not invent results when a daemon, journal or artifact is unavailable.
