# Mac mini installation — 2026-11-03

Neural Commons v1 was installed through the existing Screen Sharing session on `lupuss-Mac-mini.local`, at `/Users/lupus/projects/neural-commons`.

Verified on the Mac mini:

- Source archive SHA-256 matched the laptop package.
- Rust 1.93 build and all 8 workspace tests passed.
- Current DKG `origin/testnet-canary` was fetched immediately before setup: `02a799660c19fd0fa7749bd0924706b6625ad050`.
- The documented opaque-source compatibility patch applied and DKG runtime build passed with Node `v24.19.0`.
- `./nc.command --help` passed. The wrapper selects Node 24 and uses a process-local Git HTTPS rewrite, preserving existing Git/SSH settings.
- Existing `~/projects/dkg-v9` working-tree status and binary diff hashes matched before and after setup.

Run on the Mac mini:

```sh
cd ~/projects/neural-commons
./nc.command --help
```

`./nc.command demo` starts the existing two-participant integration test locally on the Mac mini. It was not run as part of this installation. DKG exchange between the laptop and Mac mini subsequently [passed](CROSS-HOST.md). No persistent Neural Commons or DKG services were started by this installation.

The Mac mini has approximately 9.6 GB of free space after setup. Rust 1.93 is pinned in that installation's `rust-toolchain.toml`; the normal system toolchain and default Node are unchanged.

[Machine-returned validation evidence](validation-v1/mac-mini-install.json). Full build log on the Mac mini: `.runtime/mac-mini-install.log`.
