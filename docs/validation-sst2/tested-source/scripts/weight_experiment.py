#!/usr/bin/env python3
"""Import a frozen agent session into Rust and independently evaluate it."""
import json
import pathlib
import platform
import subprocess
import sys

from weight_agent import ROOT, sha, write

EVALUATOR = "nc/causal-lm-labels/v1"


def nc(home, *args, timeout=600):
    return json.loads(subprocess.check_output(
        [str(ROOT / "target/debug/nc"), "--home", str(home), *map(str, args)],
        text=True, timeout=timeout))


def configure(home):
    import torch, transformers, safetensors, tokenizers
    runtime = {"python": platform.python_version(), "torch": torch.__version__,
               "transformers": transformers.__version__, "safetensors": safetensors.__version__,
               "tokenizers": tokenizers.__version__, "device": "cpu", "dtype": "float32",
               "threads": 4, "attention": "eager"}
    home = pathlib.Path(home)
    home.mkdir(parents=True, exist_ok=True)
    lock = home / "llm-runtime.json"
    write(lock, runtime)
    adapter = ROOT / "evaluators/causal_lm.py"
    identity = [adapter, ROOT / "evaluators/llm_runtime.py", lock]
    path = home / "evaluators.json"
    runners = json.loads(path.read_text()) if path.exists() else {}
    backend = "python-transformers-cpu-f32/" + sha(lock)
    runners[EVALUATOR] = {"program": str(pathlib.Path(sys.executable).resolve()),
                          "args": [str(adapter)], "identity_files": list(map(str, identity)),
                          "backend": backend, "max_timeout_ms": 300000, "max_output_bytes": 1048576}
    write(path, runners)


def experiment(home, directory, session_directory):
    session = json.loads((session_directory / "session.json").read_text())
    commitment = session["commitment"]
    paths = {"target": directory / "model/model.safetensors", "config": directory / "config.json",
             "development": directory / "development.json", "heldout": directory / "heldout.json",
             "policy": directory / "policy.json"}
    for name, path in paths.items():
        if sha(path) != commitment[name + "_sha256"]:
            raise ValueError("experiment commitment mismatch: " + name)
    for name, digest in commitment.get("inference_file_sha256", {}).items():
        if sha(directory / "model" / name) != digest:
            raise ValueError("inference file commitment mismatch: " + name)
    if "selection_sha256" in commitment:
        if sha(directory / "selection.json") != commitment["selection_sha256"]:
            raise ValueError("selection data commitment mismatch")
        if sha(session_directory / "selection-report.json") != session["selection_report_sha256"]:
            raise ValueError("selection report mismatch")
    if sha(session_directory / "transcript.jsonl") != session["transcript_sha256"]:
        raise ValueError("controller transcript mismatch")
    if sha(session_directory / "candidate.safetensors") != session["candidate_sha256"]:
        raise ValueError("frozen candidate mismatch")
    configure(home)
    mapping = {"config": str(directory / "config.json"), "model_config": str(directory / "model/config.json"),
               "tokenizer": str(directory / "model/tokenizer.json"),
               "tokenizer_config": str(directory / "model/tokenizer_config.json"),
               "special_tokens": str(directory / "model/special_tokens_map.json"),
               "source": str(directory / "source.json")}
    mapping_path = session_directory / "mapping.json"
    write(mapping_path, mapping)
    base = nc(home, "register", paths["target"], "--inference-artifacts", mapping_path)["checkpoint"]
    candidate = nc(home, "register", session_directory / "candidate.safetensors", "--inference-artifacts", mapping_path)["checkpoint"]
    patch = nc(home, "patch", "diff", base, candidate, "--hypothesis", session["selected"]["hypothesis"])["patch"]
    rebuilt = nc(home, "patch", "apply", base, patch)["checkpoint"]
    if rebuilt != candidate:
        raise ValueError("Rust patch reconstruction differs from frozen candidate")
    put = lambda path: nc(home, "put", path)["artifact"]
    evidence_paths = [session_directory / name for name in ["session.json", "transcript.jsonl", "commitment.json"]]
    evidence_paths += [directory / "development.json", home / "llm-runtime.json"]
    for name, digest in session.get("extra_evidence", {}).items():
        if pathlib.Path(name).name != name:
            raise ValueError("invalid evidence filename")
        path = session_directory / name
        if sha(path) != digest:
            raise ValueError("extra evidence mismatch: " + name)
        evidence_paths.append(path)
    if "selection_sha256" in commitment:
        evidence_paths += [directory / "selection.json", session_directory / "selection-report.json"]
    evaluation_config = json.loads(paths["config"].read_text())
    identity = nc(home, "evaluators")[EVALUATOR]
    spec = {"schema": "nc/evaluation-spec/v1", "base": base, "candidate": candidate, "patch": patch,
            "evaluator": EVALUATOR, "executable": identity["build"], "dataset": put(paths["heldout"]),
            "config": put(paths["config"]), "policy": put(paths["policy"]), "seed": 17,
            "backend": identity["backend"], "timeout_ms": 300000, "max_samples": evaluation_config["max_samples"],
            "max_artifact_bytes": 0, "metric": evaluation_config["metric"],
            "evidence": [put(path) for path in evidence_paths]}
    spec_path = session_directory / "spec.json"
    write(spec_path, spec)
    spec_id = put(spec_path)
    evaluation = nc(home, "evaluate", spec_id)
    result = {"spec": spec_id, "evaluation": evaluation, "base": base, "candidate": candidate,
              "patch": patch, "rust_reconstruction_matches": True,
              "changed_parameters": session["changed_parameters"], "controller": commitment["controller"],
              "backend": commitment["backend"], "evidence": spec["evidence"]}
    write(session_directory / "result.json", result)
    return result
