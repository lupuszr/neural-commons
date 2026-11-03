# Neural Commons

Collaborative neural-network weight changes through OriginTrail DKG. Rust provides an architecture-independent registry and patch engine over named tensors; operator-configured evaluators measure behavior. Graph Computer is not a dependency.

V1 supports large and sharded Safetensors checkpoints, bounded-memory file processing, F32/F16/BF16 region patches and diffs, DKG-native artifact transfer, reproducible evaluator processes, durable local history, CLI operations and a local UI.

Requires Rust 1.93, Python 3.9+, Node 24, pnpm 10 and native build tools (Xcode Command Line Tools on macOS or a C/C++ toolchain on Linux).

```sh
git clone https://github.com/lupuszr/neural-commons.git
cd neural-commons
# Skip this clone if you already have a DKG checkout at this path.
git clone https://github.com/OriginTrail/dkg.git ~/projects/dkg-v9
python3 scripts/setup.py --dkg-repo ~/projects/dkg-v9
cargo run --locked --bin nc -- demo
```

The integration command starts two isolated DKG participants and a disposable local EVM, tests collaboration and recovery, and stops its services. It includes a trained classifier on real Iris data as well as labelled synthetic regression fixtures. No paid public-chain publication occurs.

- [V1 setup, commands, evaluator contract and limitations](docs/V1.md)
- [V1 validation evidence](docs/V1-VALIDATION.md)
- [Accepted v1 scope](docs/V1-PLAN.md)
- [Original plan](PLAN.md) and [first-delivery evidence](docs/VALIDATION.md)

Setup uses a separate DKG checkout and a [small local compatibility patch](patches/dkg-opaque-source-read.patch) for reading opaque source artifacts. It preserves the original dirty checkout. The patch is not claimed to be merged upstream. Rust dependencies are pinned in Cargo.lock.

[Validation between the laptop and Mac mini passed](docs/CROSS-HOST.md), including independent evaluation, native DKG checkpoint transfer and remote restart recovery. This does not establish production readiness or independent institutional trust.

Licensed under [Apache-2.0](LICENSE).
