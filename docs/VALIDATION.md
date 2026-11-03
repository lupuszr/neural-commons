# Local delivery validation

Validated on 3 November 2026 on macOS/aarch64. This is local implementation and integration evidence. Hosted CI and external deployment were not performed.

## Reproduce

```sh
python3 scripts/setup.py --dkg-repo ~/projects/dkg-v9
cargo run --locked --bin nc -- demo
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
```

Both setup and the demo command completed locally. Setup was also rerun against the existing isolated dependency checkout; this is not a second clean-machine installation test. Dependencies require network access and the prerequisites in the README. Each demo fetches current `origin/testnet-canary` immediately before testing and checks that it matches the built detached checkout.

Recorded DKG revision: `4e4455d8719cea05479e7f1e59f0b96a7d0d1f00` (DKG 10.0.27). Toolchain: Rust 1.93.0, Node v24.11.1 and pnpm 10.30.3. Rust dependencies are pinned in Cargo.lock. [Source manifest](validation/source-manifest.json) identifies the delivered source files; [build record](validation/build.json) identifies the DKG checkout and Node runtime.

## Evidence

- [Rust tests](validation/rust-tests.txt): six tests passed. Coverage includes unrelated tensor layouts and ranks, deterministic edits with every untargeted byte preserved, rejected invalid patches, actual held-out repair/regression behavior, authenticated graph placement, adversarial artifact transport, job recovery, retained retry history and publication reconciliation.
- [Clippy](validation/clippy.txt): workspace/all-targets passed with warnings denied. Rust formatting, JavaScript syntax and Python compilation checks passed.
- [Real DKG demo](validation/demo.json): two distinct agent identities and daemon homes, real HTTP/libp2p transport, signed Context Graph policy, a disposable Hardhat EVM for authority resolution, and independent artifact stores. Participant B begins without A's artifacts, discovers proposals through DKG, downloads and verifies their contents, executes fresh evaluator subprocesses and shares reports. A reads B's reports and reviews through its own DKG daemon. ModelVersion, Hypothesis, PatchProposal, Evaluation, Review and DerivedVersion records traverse this workflow.
- The controlled repair passes the predetermined policy and the harmful patch fails on both participants. Reports bind exact specs, build identities, inputs, policy and outputs; distinct process IDs record separate executions. Duplicate reproduction reuses existing computation and publication.
- The integration run kills a supervisor and its worker, observes an explicit interrupted state and successfully retries in a fresh process. A simulated lost publication response is reconciled against a real existing DKG record. Missing artifacts, missing API authentication and denied private-graph access fail explicitly.
- [Unavailable DKG check](validation/dkg-unavailable.json): fetching after the daemons stop returns an explicit connection error, not an empty or successful result.
- [Browser check](validation/browser-ui.json): Chromium loaded real checkpoint, tensor, evaluation and provenance records; wrong-token access was rejected; desktop 1440×1000 and mobile 390×844 layouts rendered without JavaScript errors or mobile horizontal overflow. Run `node scripts/ui_check.cjs <completed-demo>/a` with Playwright Chromium installed to repeat it.
- [Checkout preservation](validation/dkg-checkout-preservation.json): all 45 original dirty status entries remain unchanged and all 41 individually captured file hashes match. Four untracked directory entries were captured at status level only. The source checkout was not switched or reset. Build and generated deployment files stayed in the isolated checkout; tracked deployment addresses were restored after each local deployment.

Demo services stop when the command finishes. Runtime logs, private credentials and full local databases stay in ignored `.runtime/`; only nonsecret validation evidence is copied here.

## Delivery boundaries

The generic engine supports Safetensors inventories and bounded F32 region replacement. The reference evaluator is a small native Rust CPU MLP adapter behind the replaceable evaluator contract; Candle was a proposed dependency and is not required by this implementation. There is no Graph Computer dependency.

The fixture demonstrates controlled repair of a known function, not discovery of a new model capability. Two participants on one machine establish separate transport, storage and execution, not organizational independence. Collaboration records use Shared Working Memory; these results do not claim public-chain Verifiable Memory finality. The client trusts the pinned authenticated DKG daemon's verified author-catalog projection. DKG's TCP listener binds all interfaces; the Rust API/artifact services and local chain bind loopback. Production isolation, external deployment, arbitrary architectures, large checkpoints, quantized edits and remote evaluator execution remain outside this delivery.
