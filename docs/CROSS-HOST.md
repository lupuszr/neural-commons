# Two-host validation — passed 2026-11-03

Actual DKG exchange passed between `OTLegends-MacBook-Pro-5.local` and `lupuss-Mac-mini.local`, with one daemon per machine, separate identities, credentials and storage. Both fetched `origin/testnet-canary` immediately before the test and used `02a799660c19fd0fa7749bd0924706b6625ad050` with the documented opaque-source compatibility patch.

## Verified results

- Mac mini began with an empty client artifact store.
- Controlled repair passed on both hosts; controlled regression failed on both. Base and candidate metrics matched exactly.
- Mac mini independently fetched the model, patch and evaluation inputs through DKG, executed the evaluator and published its report and review. The laptop fetched both through DKG and checked authorship/relationships.
- Repeating reproduction reused the same report.
- A 100,663,385-byte (96 MiB plus header) synthetic checkpoint crossed the native DKG peer protocol and was SHA-256 verified on the Mac mini.
- The Mac mini daemon was stopped and restarted with the same identity. A fresh client artifact store then recovered and hash-verified the checkpoint again.
- Both daemon processes, the disposable local EVM and the temporary coordination endpoint were stopped afterward. The remote Terminal returned to its shell prompt after cleanup.

[Full evidence](validation-v1/cross-host.json). Laptop run: `.runtime/cross-host-20261103-122714`; Mac mini run: `/Users/lupus/projects/neural-commons/.runtime/cross-host-20261103-123135`.

## Test boundary

The runner is `scripts/cross_host.py`. A temporary IP-restricted HTTP endpoint coordinates fixed test operations, installs the same evaluator binary on the Mac mini and forwards disposable local EVM RPC. Model, patch, dataset and evidence artifacts travel through native DKG libp2p; daemon API bearer tokens stay on their respective hosts. The evaluator executable is identical and hash-verified because evaluation specifications bind its exact build. The remote binary is isolated in the test run directory and does not replace the installed build.

This proves physical separation and native DKG exchange on the same LAN. The behavioral tests are labelled synthetic fixtures; the trained Iris external-evaluator experiment remains single-host evidence. Public-chain finality, independently governed operators, WAN/NAT conditions and production load/security remain unverified. No Graph Computer was used.

## Reproduce

Verify LAN addresses and build current `origin/testnet-canary` on both hosts first. Start on the laptop:

```sh
python3 scripts/cross_host.py --bind 192.168.1.236 --peer 192.168.1.237
```

After `READY_FOR_MAC_MINI`, execute these separately on the Mac mini:

```sh
curl -f http://192.168.1.236:18762/worker.py -o /tmp/nctest.py
python3 /tmp/nctest.py --root /Users/lupus/projects/neural-commons --worker http://192.168.1.236:18762
```

The runner saves results under `.runtime/cross-host-*` and stops its own daemon children on exit. It assumes the installed Node 24 nvm runtime on the Mac mini. It is a controlled LAN validation tool, not a production management service.
