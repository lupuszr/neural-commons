#!/usr/bin/env python3
"""Two local DKG participants reproduce an actual LLM controller's frozen edit."""
import argparse
import json
import os
import pathlib
import secrets
import signal
import subprocess
import time

import local_chain
from demo import port
from dkg_runtime import ROOT, SOURCE, config, setup_network, launch, wait_ready, request
from weight_experiment import configure, experiment, nc
from weight_agent import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=pathlib.Path, required=True)
    parser.add_argument("--session", type=pathlib.Path, required=True)
    parser.add_argument("--run-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=False)
    os.chmod(run, 0o700)
    evidence = {"schema": "nc/weight-dkg-validation/v1", "status": "running",
                "scope": "two separate local DKG daemons and evaluator processes on one physical machine",
                "chain": "disposable local Hardhat EVM; no public-chain finality",
                "run": str(run)}
    processes, logs = [], []
    def log_for(path):
        handle = open(path, "w")
        logs.append(handle)
        return handle
    def eventually(fn, seconds=120):
        deadline, last = time.monotonic() + seconds, None
        while time.monotonic() < deadline:
            try:
                return fn()
            except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
                last = error
                time.sleep(1)
        raise RuntimeError(f"readback deadline: {last}")
    try:
        subprocess.run(["git", "fetch", "origin", "testnet-canary"], cwd=SOURCE, check=True, capture_output=True)
        current = subprocess.check_output(["git", "rev-parse", "origin/testnet-canary"], cwd=SOURCE, text=True).strip()
        built = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
        if current != built:
            raise RuntimeError("DKG canary changed: rebuild the isolated checkout with scripts/setup.py")
        evidence["dkg_revision"] = built
        evidence["dkg_source_patch"] = subprocess.check_output(["git", "diff"], cwd=SOURCE, text=True)
        setup_network()
        chain, chain_token = local_chain.start(run, port(), processes, log_for)
        homes, dkg_homes = [run / "a", run / "b"], [run / "dkg-a", run / "dkg-b"]
        apis, peers, identities = [port(), port()], [port(), port()], []
        for i in range(2):
            config(dkg_homes[i], apis[i], peers[i], 201 + i, chain)
            local_chain.fund(dkg_homes[i], chain, chain_token)
            process = launch(dkg_homes[i], log_for(run / f"dkg-{i}.log"))
            processes.append(process)
            identities.append(wait_ready(dkg_homes[i], apis[i], process))
            homes[i].mkdir(mode=0o700)
            token = homes[i] / "ui.token"
            token.write_text(secrets.token_hex(32))
            token.chmod(0o600)
        assert identities[0]["agentAddress"] != identities[1]["agentAddress"]
        graph = identities[0]["agentAddress"].lower() + "/nc-weight-agent-" + secrets.token_hex(8)
        request(dkg_homes[1], apis[1], "/api/connect", {"multiaddr": f'/ip4/127.0.0.1/tcp/{peers[0]}/p2p/{identities[0]["peerId"]}'}, admin=True)
        request(dkg_homes[0], apis[0], "/api/context-graph/create", {"id": graph, "name": "Neural Commons weight-space agent", "accessPolicy": 0, "publishPolicy": 1, "register": True})
        eventually(lambda: request(dkg_homes[1], apis[1], "/api/context-graph/subscribe", {"contextGraphId": graph}))
        for i in range(2):
            write(homes[i] / "config.json", {"dkg_url": f"http://127.0.0.1:{apis[i]}",
                  "dkg_token_file": str(dkg_homes[i] / "agent.token"), "context_graph": graph,
                  "artifact_origin": "dkg", "artifact_token_file": str(homes[i] / "ui.token"),
                  "trusted_artifact_origin": None, "trusted_artifact_token_file": None})
        evidence["identities"], evidence["context_graph"] = identities, graph
        local = experiment(homes[0], args.directory.resolve(), args.session.resolve())
        evidence["a"] = local
        write(run / "validation.json", evidence)
        assert local["evaluation"]["evaluation"]["status"] in ["passed", "failed"], local
        configure(homes[1])
        assert not (homes[1] / "artifacts").exists()
        evidence["b_started_without_artifacts"] = True
        print("Local held-out evaluation complete; publishing real LLM checkpoint and agent provenance", flush=True)
        proposal = nc(homes[0], "propose", local["spec"])
        evidence["proposal"] = proposal
        write(run / "validation.json", evidence)
        remote = eventually(lambda: nc(homes[1], "reproduce", proposal["record"]))
        evidence["b"] = remote
        assert remote["evaluation"]["status"] == local["evaluation"]["evaluation"]["status"], remote
        assert remote["evaluation"]["scores"] == local["evaluation"]["evaluation"]["scores"], remote
        assert remote["evaluation"]["outputs"] == local["evaluation"]["evaluation"]["outputs"]
        assert remote["evaluation"]["process_id"] != local["evaluation"]["evaluation"]["process_id"]
        evidence["a_readback"] = eventually(lambda: nc(homes[0], "fetch", remote["publication"]["record"]))
        evidence["review_readback"] = eventually(lambda: nc(homes[0], "fetch", remote["review"]["record"]))
        assert evidence["a_readback"]["author"] == identities[1]["agentAddress"]
        assert evidence["a_readback"]["relates_to"] == proposal["record"]
        for artifact in local["evidence"]:
            assert (homes[1] / "artifacts" / artifact).is_file()
        evidence["provenance_transferred"] = True
        evidence["status"] = "passed"
        print("Independent evaluator reproduced identical scores and output artifact through DKG", flush=True)
    except Exception as error:
        evidence["status"], evidence["error"] = "failed", str(error)
        raise
    finally:
        for process in reversed(processes):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        for handle in logs:
            handle.close()
        evidence["services_stopped"] = True
        write(run / "validation.json", evidence)


if __name__ == "__main__":
    main()
