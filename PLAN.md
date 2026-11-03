# Neural Commons — implementation plan

Date: 2026-11-02

Status: original first delivery completed; v1 authorized on 2026-11-03 and tracked in `docs/V1-PLAN.md`; final validation evidence is recorded in `docs/VALIDATION.md`. The scope below remains the accepted implementation plan.

## Objective

Build a Rust application where participants register neural-network checkpoints, propose weight patches, reproduce evaluations, and share the resulting evidence through OriginTrail DKG.

The first delivery should demonstrate the complete workflow with real tensor changes, real evaluation, and two local participants. A small CPU model is a demo fixture, not a restriction on the registry, patch format, DKG schema, or application.

The user explicitly removed Graph Computer from this project. Do not introduce its runtime, SDK, approval model, or a replacement workflow engine.

## Essential design decision

Weights are named numerical tensors. A model additionally needs an architecture, computation rules, input processing, and an evaluation procedure.

Keep three layers separate:

1. **Generic tensor layer:** inspect, identify, diff, patch, transfer, and version supported tensor representations without knowing the model architecture.
2. **Evaluator layer:** execute a particular model architecture and score its behavior through a versioned adapter contract.
3. **Semantic evidence layer:** record architecture descriptions, hypotheses about behavior, patches, evaluations, and reviews in DKG.

Never infer a tensor's behavioral meaning from its shape or name alone. Architecture labels are optional metadata; behavioral explanations are attributed hypotheses supported by evidence.

Adding another supported checkpoint must not require edits to the patch engine or DKG schema. It may require a new evaluator or format adapter.

## First delivery

- A generic Safetensors checkpoint importer, tensor inventory, and immutable checkpoint manifests.
- Bounded tensor patch generation, validation, application, and output verification.
- A replaceable evaluator interface with one small CPU evaluator implemented in Rust.
- Two local participants with distinct identities, work directories, and fresh evaluation processes.
- Actual DKG write/share/readback of proposals and evaluations.
- A minimal web interface showing tensor maps, proposals, evidence, and version lineage.
- CLI commands, reproducible fixtures, focused tests, and a one-command local demonstration.

Two local participants demonstrate transport and separate execution. They do not establish independent institutional trust or real-world model improvement.

## Repository layout

```text
crates/
  core/          # manifests, identifiers, tensor inspection, patch engine
  evaluator/     # evaluator contract and reference CPU evaluator
  dkg-client/    # supported daemon API, identity handling, RDF mapping
  app/           # CLI, HTTP API, bounded jobs, SQLite journal
web/             # small UI served by the Rust application
fixtures/        # heterogeneous tensor fixtures and behavioral demo
scripts/         # local setup, demo, replay
docs/            # protocol details and validation evidence
```

Proposed dependencies: Safetensors for tensor serialization, Candle for the reference Rust evaluator, a conventional Rust HTTP stack, and SQLite for local job state. Verify and pin compatible dependency versions when implementation begins.

The DKG daemon remains an external dependency. Do not reimplement the DKG protocol or turn this project into a new DKG node.

## Checkpoints and artifacts

A checkpoint manifest records a schema version, exact artifact hashes, tensor inventory, serialization format, and optional architecture/configuration/tokenizer references. Include all required inference artifacts in the evaluator input identity.

Begin with a single Safetensors file; leave sharded manifests as a compatible extension unless needed by the chosen demo. Support arbitrary tensor names and supported ranks, with no hardcoded Qwen names or layer counts.

Declare supported dtypes explicitly. At minimum, implement F32 editing correctly; unsupported representations must return a precise error. Preserve untouched supported file contents semantically without silent casts. Packed/quantized weight editing needs a dedicated adapter and is out of the first delivery.

Store binary checkpoints, patch payloads, and evaluation artifacts in a content-addressed artifact store. DKG contains their hashes, authorized locations, ownership, and provenance relationships, not one RDF triple per weight.

Provide actual artifact delivery between the demo participants. Participant B must download and verify files into its own store rather than silently reading A's working directory. Bind the artifact service to the isolated demo environment and restrict access to its configured participants. Verify hashes before use; unavailable artifacts remain explicit failures.

## Patch contract

Each immutable patch manifest includes:

- Schema version, author identity, parent checkpoint digest, and patch digest.
- Exact tensor name, dtype, shape, and selected region for every operation.
- Operation kind and payload digest.
- Expected result checkpoint digest.
- Optional hypothesis and evidence references.

Implement region replacement first. Its semantics can be byte-exact for supported representations and allow a producer to submit any computed weight change without prescribing how it was discovered. Add numerical delta operations only after rounding, overflow, and dtype rules are specified and tested.

Validate base digest, bounds, dimensions, payload lengths, overlapping writes, finite numerical values, and resource limits. Reject ambiguous overlapping operations in version one. Never apply a patch to a different checkpoint or overwrite the base artifact.

Output serialization and hashing must be deterministic under a versioned implementation. Verify that all non-target tensor values are unchanged. Stage output and atomically make it available only after validation succeeds.

Do not automatically merge patches, including patches that touch disjoint regions. Any composition produces a new candidate requiring a new evaluation.

## Evaluator contract

Define a versioned `EvaluationSpec` containing:

- Checkpoint manifest digest and necessary inference artifact digests.
- Evaluator identity/version and executable or build digest.
- Dataset/split digest and metric definitions.
- Seed, inference settings, environment/backend identity, timeout, and resource limits.
- Acceptance-policy version where a verdict is requested.

Return an `EvaluationReport` with measured metrics, artifact references, execution status, observed environment, and errors. Distinguish passed, failed, interrupted, and unavailable. Infrastructure failures are not model-quality failures.

Implement a Rust CPU adapter first. Define a clean extension boundary for a configured subprocess or remote evaluator later; proposal manifests must never be able to choose arbitrary executable commands on a verifier's machine.

Compare the base and candidate using the same pinned evaluation specification. Define acceptance thresholds before final evaluation. Use held-out test inputs separate from patch-development inputs.

Use byte hashes for artifact integrity. For numeric outputs, specify metric tolerances and record backend differences rather than claiming every platform is bit-identical.

## DKG data model and integration

Use versioned RDF entities for:

- `ModelVersion`: checkpoint identity, tensor descriptors, optional architecture metadata.
- `Hypothesis`: attributed claim about a model region or behavior.
- `PatchProposal`: exact base, target regions, payload references, author, and rationale.
- `Evaluation`: evaluator/input identities, measured results, status, and supporting artifacts.
- `Review`: participant assessment bound to exact evidence and policy.
- `DerivedVersion`: resulting checkpoint and ordered patch lineage.

A Context Graph groups the collaboration. DKG-authenticated authorship must be derived from the selected participant identity, not an arbitrary client-supplied display name. Keep a local job identifier distinct from a cryptographic content identity and from a DKG asset identifier.

Use the existing daemon's supported authenticated APIs and Knowledge Asset lifecycle. Discover current route and authentication contracts from the pinned source before implementing the Rust client; do not copy historical endpoints blindly.

The initial collaboration targets Shared Working Memory with verified readback on the second participant. Do not label this as on-chain Verifiable Memory finality. Do not perform paid public-chain publication as part of the default demo.

Keep authorization scoped to the test Context Graph. A valid signature or hash proves authorship/integrity, not model quality or privacy. A verifier must actually re-run the evaluation.

## Local jobs and recovery

Use a bounded local worker queue and SQLite journal, not a distributed workflow engine.

Persist stable job IDs and exact inputs before execution. Journal evaluation state and DKG publication state separately so a completed evaluation can retry publication without repeating computation.

Use deterministic asset identities or supported lookup/reconciliation to prevent duplicate records. After an uncertain write response, reconcile before retrying. Keep unresolved publication visible as pending/unknown.

On restart, report interrupted computation accurately; resume/retry according to an explicit policy. Never convert an incomplete job into a successful evaluation.

## UI and CLI

Default UI is a tensor inventory/map that works without architecture knowledge. An optional architecture descriptor can group tensors into layers and modules.

Show:

- Registered checkpoints and their exact versions.
- Tensor names, shapes, dtypes, and targeted patch regions.
- Proposal list and attributed hypothesis.
- Base/candidate evaluation results, reproducibility details, and regression verdicts.
- Version lineage and DKG sharing/readback state.

Keep author claims, local evaluations, and another participant's reproduction visibly distinct. Never show mock validation as a live result.

Proposed CLI verbs: `inspect`, `register`, `patch create`, `patch apply`, `evaluate`, `share`, `reproduce`, `serve`, and `demo`. These are planned interfaces, not existing commands.

The earlier UI concept is available at `/Users/otlegend/projects/dkg-v9/output/neural-map-ui.html`. Treat it as a visual reference only: its Qwen layer count, identifiers, statuses, and evidence are illustrative and must not become product assumptions.

## Delivery sequence

1. **Integration spike and contracts:** establish the Rust workspace; validate the actual DKG authenticated write/share/readback path between two isolated participants; define checkpoint, patch, and evaluation schemas.
2. **Generic tensor engine:** inventory/import, manifests, bounded region replacement, deterministic artifacts, rejection paths. Exercise multiple unrelated tensor layouts before adding an evaluator.
3. **Behavioral evaluation:** implement one CPU evaluator and a deliberately labelled controlled-repair fixture, a harmful patch, and held-out test inputs.
4. **Collaboration and recovery:** publish proposals, fetch and verify artifacts on B, repeat evaluation, publish reports, verify readback, and exercise restart/reconciliation.
5. **Minimal UI:** connect the previous interaction design to actual API state, using architecture-independent tensor inspection by default.
6. **Delivery checks:** run focused tests and the complete demo, document exact versions and evidence, provide commands and limitations.

Target effort is approximately one overnight session, around eight hours, subject to DKG setup. Preserve the complete CLI collaboration path before optional visual polish. Do not replace a failed real DKG integration with a mock and call the delivery complete.

## Acceptance criteria

- Inspect and patch at least two unrelated tensor layouts, including different names/shapes/ranks, with the same core code and schema.
- Apply a valid patch reproducibly and confirm all untargeted values are preserved.
- Reject wrong base, tampered payload, out-of-bounds regions, shape/dtype mismatch, unsupported representation, and oversized input.
- A declared controlled repair passes the predetermined behavioral policy; a regression patch fails it.
- Participant B discovers A's proposal through DKG, independently downloads artifacts, verifies them, executes its evaluator, and shares its report.
- The report binds the exact checkpoint, patch, evaluator, dataset, settings, and acceptance-policy identities.
- Duplicate requests and restart do not lose history, fabricate success, or silently duplicate published evaluations.
- Missing DKG access, denied graph access, missing artifacts, and interrupted evaluators are represented explicitly.
- UI uses actual records; demonstrative fixtures are labelled.
- One documented demo command reproduces the local workflow from a clean project setup, with explicit prerequisites.

## Non-goals for the first delivery

- Graph Computer integration.
- A universal inference engine for every architecture.
- Packed/quantized tensor mutation or arbitrary model conversion.
- Large-model training, automatic architecture discovery, or automatic patch merging.
- Autonomous discovery of novel LLM capabilities or a claim of reproducing the cited Qwen result.
- Tokens, incentives, external deployment, or production consensus.

## Validation and handoff

Use focused core tests for patch integrity and unchanged regions, evaluator tests for actual behavior, and integration tests for real DKG transfer, authorship, replay, and recovery. Avoid tests that only mirror implementation details.

Before DKG integration testing, fetch the latest `origin/testnet-canary`, use that fetched revision in an isolated checkout, and record its SHA. Preserve the existing dirty checkout at `/Users/otlegend/projects/dkg-v9`; do not switch or reset it.

Deliver a validation record separating local unit tests, local multi-participant DKG evidence, CI (if configured), and any untested deployment assumptions. Local actors are not evidence of third-party endorsement.

This project creation request authorizes saving the plan and opening a new T3 thread. The new thread is a context handoff; start implementation only when the user requests it there or subsequently authorizes execution.

## References

- Safetensors: https://huggingface.co/docs/safetensors/index
- Candle: https://github.com/huggingface/candle
- Research motivation: https://rikiyat.github.io/blog/weight-space-programming/

The research motivates the workflow. Its reported performance is not an acceptance baseline for this infrastructure project.
