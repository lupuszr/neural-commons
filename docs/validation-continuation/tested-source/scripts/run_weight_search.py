#!/usr/bin/env python3
"""Run a bounded controller search and validation selection; do not open final test."""
import argparse
import pathlib
import subprocess
import sys

from weight_agent import ROOT, sha


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--backend", choices=["codex", "openai"], required=True)
    parser.add_argument("--controller-model", required=True)
    parser.add_argument("--max-probes", type=int, default=16)
    parser.add_argument("--min-probes", type=int, default=12)
    parser.add_argument("--max-rounds", type=int, default=28)
    args = parser.parse_args()
    directory, output = args.directory.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(ROOT / "scripts/weight_agent.py"),
               "--model", str(directory / "model"), "--config", str(directory / "config.json"),
               "--development", str(directory / "development.json"), "--source", str(directory / "source.json"),
               "--output", str(output / "proposals"), "--backend", args.backend,
               "--controller-model", args.controller_model, "--max-probes", str(args.max_probes),
               "--min-probes", str(args.min_probes), "--max-rounds", str(args.max_rounds),
               "--controller-timeout", "240"]
    # Only hash the reserved files here; their examples never enter controller input.
    for name in ["heldout", "policy", "selection"]:
        command += ["--" + name + "-sha256", sha(directory / (name + ".json"))]
    if (directory / "handoff.json").exists():
        command += ["--handoff", str(directory / "handoff.json")]
    subprocess.run(command, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/select_weight_candidate.py"),
                    "--directory", str(directory), "--source", str(output / "proposals"),
                    "--output", str(output / "selected")], check=True)
    print("Frozen candidate session:", output / "selected")
