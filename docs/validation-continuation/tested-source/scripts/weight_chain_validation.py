#!/usr/bin/env python3
"""Two different controllers build a verified chain of weight edits through DKG."""
import argparse
import json
import os
import pathlib
import secrets
import signal
import subprocess
import time
import shutil
import sys
from prepare_agnews_continuation import prepare as prepare_continuation
from weight_agent import sha

import local_chain
from demo import port
from dkg_runtime import ROOT, SOURCE, config, setup_network, launch, wait_ready, request
from weight_experiment import configure, experiment, nc
from weight_agent import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-directory", type=pathlib.Path, required=True)
    parser.add_argument("--parent-session", type=pathlib.Path, required=True)
    parser.add_argument("--backend", choices=["codex", "openai"], required=True)
    parser.add_argument("--controller-model", required=True)
    parser.add_argument("--run-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=False)
    os.chmod(run, 0o700)
    evidence = {"schema": "nc/weight-chain-validation/v1", "status": "running",
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
        parent_session = json.loads((args.parent_session / "session.json").read_text())
        if parent_session["commitment"]["controller"] == args.controller_model:
            raise ValueError("this validation requires a different second controller model")
        parent_copy = run / "parent-session"
        parent_copy.mkdir()
        for path in args.parent_session.iterdir():
            if path.is_file():
                if path.name == "candidate.safetensors":
                    (parent_copy / path.name).symlink_to(path.resolve())
                else:
                    shutil.copyfile(path, parent_copy / path.name)
        parent_local = experiment(homes[0], args.parent_directory.resolve(), parent_copy)
        if parent_local["evaluation"]["evaluation"]["status"] != "passed":
            raise ValueError("frozen parent no longer passes its own evaluation")
        evidence["parent_local"] = parent_local
        configure(homes[1])
        assert not (homes[1] / "artifacts").exists()
        evidence["b_started_without_artifacts"] = True
        proposal = nc(homes[0], "propose", parent_local["spec"])
        evidence["parent_proposal"] = proposal
        write(run / "validation.json", evidence)
        print("Parent published; participant B is receiving and independently reproducing it", flush=True)
        parent_remote = eventually(lambda: nc(homes[1], "reproduce", proposal["record"]))
        evidence["parent_remote"] = parent_remote
        assert parent_remote["evaluation"]["outputs"] == parent_local["evaluation"]["evaluation"]["outputs"]
        assert parent_remote["evaluation"]["scores"] == parent_local["evaluation"]["evaluation"]["scores"]
        assert parent_remote["evaluation"]["status"] == "passed"
        directory = run / "continuation"
        handoff = prepare_continuation(homes[1], proposal["record"], parent_remote["report"],
                                       args.parent_directory.resolve(), directory)
        evidence["handoff_sha256"] = sha(directory / "handoff.json")
        evidence["inherited_checkpoint"] = handoff["candidate_checkpoint"]
        write(run / "validation.json", evidence)
        print("B verified the parent diff and inherited model; starting the second controller", flush=True)
        search = run / "search"
        subprocess.run([sys.executable, str(ROOT / "scripts/run_weight_search.py"),
                        "--directory", str(directory), "--output", str(search),
                        "--backend", args.backend, "--controller-model", args.controller_model,
                        "--max-probes", "20", "--min-probes", "12", "--max-rounds", "32"], check=True)
        child = experiment(homes[1], directory, search / "selected")
        evidence["child_local"] = child
        assert child["base"] == parent_local["candidate"] == handoff["candidate_checkpoint"]
        evidence["exact_parent_checkpoint_link"] = True
        write(run / "validation.json", evidence)
        print("Second candidate frozen and tested; participant A will reproduce B's proposal", flush=True)
        child_proposal = nc(homes[1], "propose", child["spec"])
        evidence["child_proposal"] = child_proposal
        child_remote = eventually(lambda: nc(homes[0], "reproduce", child_proposal["record"]))
        evidence["child_remote"] = child_remote
        for key in ["status", "scores", "outputs"]:
            assert child_remote["evaluation"][key] == child["evaluation"]["evaluation"][key]
        assert child_remote["evaluation"]["process_id"] != child["evaluation"]["evaluation"]["process_id"]
        readback = eventually(lambda: nc(homes[1], "fetch", child_remote["publication"]["record"]))
        evidence["child_readback"] = readback
        assert readback["author"] == identities[0]["agentAddress"]
        assert readback["relates_to"] == child_proposal["record"]
        evidence["review_readback"] = eventually(lambda: nc(homes[1], "fetch", child_remote["review"]["record"]))
        assert evidence["review_readback"]["author"] == identities[0]["agentAddress"]
        assert evidence["review_readback"]["relates_to"] == child_remote["publication"]["record"]
        for digest in child["evidence"]:
            assert sha(homes[0] / "artifacts" / digest) == digest
        evidence["provenance_transferred"] = True
        evidence["model_improvement_status"] = child["evaluation"]["evaluation"]["status"]
        evidence["status"] = "passed"
        print("Verified M0 -> M1 -> M2 lineage and identical DKG reproduction; improvement verdict: " + evidence["model_improvement_status"], flush=True)
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
