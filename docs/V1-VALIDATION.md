# V1 local validation

Validated on 3 November 2026 on macOS/aarch64. Physical two-machine validation was subsequently completed; see [cross-host evidence](CROSS-HOST.md). This document records local evidence, not hosted CI, production qualification or third-party endorsement.

## Build and source

DKG base: `f425a69eeb8f74bf94ed846bfa161ed3ec44b1bf`, fetched from `origin/testnet-canary` immediately before integration. The build includes the narrow [opaque-source read compatibility patch](../patches/dkg-opaque-source-read.patch); it is not upstream-merged. [Build identity](validation-v1/build.json) records the patch hash and Node runtime. Rust dependencies are locked; Rust 1.93.0 and Node v24.11.1 were used. Setup was rerun successfully against the isolated dependency checkout. Installation, build and eight Rust tests subsequently passed on the Mac mini; see [installation evidence](MAC-MINI.md).

[Source hashes](validation-v1/source-manifest.json) identify the delivered application, adapters, scripts and compatibility patch. The existing source DKG checkout retained all 45 dirty status entries and all 41 individually captured file hashes. Four untracked directory entries were checked at status level only. See [preservation evidence](validation-v1/dkg-checkout-preservation.json).

## Results

- [Eight Rust tests passed](validation-v1/rust-tests.txt). They cover generic layouts, invalid/tampered patches, an 80 MiB checkpoint, exact reconstruction/export, sharded F16 and BF16 replacements, nonfinite values, unsafe shard paths, authenticated DKG graph placement, external evaluator identity/output/deadline checks, actual fixture behavior and durable journal history.
- [Clippy passed](validation-v1/clippy.txt) with warnings denied. Rust formatting, Python compilation and JavaScript syntax checks passed. [Four DKG metadata tests passed](validation-v1/dkg-source-tests.txt), including the skipped-source compatibility case and continued rejection of failed/in-progress extraction.
- [The real two-participant DKG integration passed](validation-v1/dkg-integration.json). Participants have distinct agent identities and separate persistent daemon/client stores. Artifact bytes travel through DKG native upload and authenticated paged peer reads. The application HTTP servers are started only after transfer/reproduction tests, so they cannot provide the peer artifact path.
- The controlled repair passes and the controlled regression fails on both participants. A separately configured Python evaluator also reproduced a genuinely trained single-layer classifier on held-out Iris data. The experiment records training/source artifacts, fixed schedule/split, policy, program/build identity and exact scores. A reads B's reports and reviews through DKG. The classifier result is a small reference experiment, not a claim about general model improvement.
- A 100,663,385-byte synthetic checkpoint was reconstructed and hash-verified on B. Deliberately corrupting a native DKG blob caused rejection before the full artifact was committed. After restoring the blob, retry succeeded using previously verified cached parts.
- Both real DKG daemons were stopped and restarted with persistent `store.options.path`. Agent identities survived; a fresh client cache recovered the large artifact through DKG. The evaluator supervisor/worker interruption test, explicit retry, duplicate reproduction and uncertain-publication reconciliation also passed. Publication stays unknown while readback is unavailable; it is not blindly resent during recovery. Artifact preparation failures remain retryable before the semantic record write begins.
- Missing local evidence, absent UI authentication and denied private-graph access failed explicitly. No public-chain publication occurred; authority resolution used a disposable local EVM and collaboration used SWM.
- [Browser checks passed](validation-v1/browser-ui.json): authenticated real records, version selection through the UI, rejection of unauthenticated mutation, desktop and mobile rendering, no JavaScript errors or horizontal overflow. Full CLI collaboration was tested separately by the integration run.

## Memory evidence

The standalone [large-checkpoint gate](validation-v1/memory.json) imports, patches, applies and verifies a 536,870,996-byte Safetensors file. `/usr/bin/time -l` recorded a maximum resident set of 4,800,512 bytes for that process, using 1 MiB I/O buffers. [Raw measurement](validation-v1/memory-time.txt) is retained. This demonstrates file-backed processing for the measured layout. Header/manifest sizes and evaluator memory remain separate resource considerations; the measurement is not a bound on every possible model or adapter.

## Reproduce and remaining checks

Commands and prerequisites are in [V1.md](V1.md). `cargo run --locked --bin nc -- demo` performs the local DKG integration and shuts down its child services. Runtime databases, source data and logs remain under ignored `.runtime/`; copied evidence contains no bearer tokens or private keys.

The GitHub Actions workflow was added but has not run on GitHub. Outstanding checks include other operating systems, production load/security qualification and independent operators. Quantized edits and diffing differently serialized/repartitioned checkpoints remain unsupported. Operators are responsible for choosing and isolating trusted evaluator programs and declaring their complete execution environment. The recorded [scope](validation-v1/scope.json) keeps these boundaries separate from passing local checks.
