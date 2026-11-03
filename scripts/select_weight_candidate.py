#!/usr/bin/env python3
"""Select among already-frozen agent proposals on a separate validation split.

This process never reads the final held-out dataset. The selection rule and data
hash were committed before the controller started. All selection results persist.
"""
import argparse
import copy
import json
import pathlib
import shutil
import torch

from weight_agent import edited_slices, load_file, load_model, save_candidate, score, sha, write
from llm_runtime import guard_passes


def choose(candidates, baseline, policy):
    eligible = [c for c in candidates if c.get("guard_passed", True) and
                c["selection"]["accuracy"] - baseline["accuracy"] >= policy["min_accuracy_improvement"] and
                c["selection"]["label_nll"] <= baseline["label_nll"] + policy["max_nll_regression"]]
    return min(eligible, key=lambda c: (-c["selection"]["accuracy"], c["selection"]["label_nll"], c["id"])) if eligible else None


def select(directory, source, output):
    output.mkdir(parents=True, exist_ok=False)
    session = json.loads((source / "session.json").read_text())
    commitment = session["commitment"]
    for name in ["config", "selection"]:
        if sha(directory / (name + ".json")) != commitment[name + "_sha256"]:
            raise ValueError(name + " commitment mismatch")
    if sha(directory / "model/model.safetensors") != commitment["target_sha256"]:
        raise ValueError("base model commitment mismatch")
    if "handoff_sha256" in commitment:
        from weight_handoff import load
        if sha(directory / "handoff.json") != commitment["handoff_sha256"]:
            raise ValueError("handoff commitment mismatch")
        load(directory, commitment["target_sha256"])
    if sha(source / "transcript.jsonl") != session["transcript_sha256"]:
        raise ValueError("transcript mismatch")
    config = json.loads((directory / "config.json").read_text())
    dataset = json.loads((directory / "selection.json").read_text())
    model, tokenizer = load_model(directory / "model")
    original = load_file(directory / "model/model.safetensors")
    sources = {**original, **{name: torch.tensor(values, dtype=torch.float32)
                              for name, values in session.get("feature_vectors", {}).items()}}
    baseline = score(model, tokenizer, dataset, config)
    if "guard" in config:
        if sha(directory / "guard.json") != commitment["guard_sha256"] or sha(directory / "guard-config.json") != commitment["guard_config_sha256"]:
            raise ValueError("guard commitment mismatch")
        guard_data = json.loads((directory / "guard.json").read_text())
        guard_config = json.loads((directory / "guard-config.json").read_text())
        guard_base = score(model, tokenizer, guard_data, guard_config)
    results = []
    for candidate in session["candidates"]:
        model.load_state_dict(original, strict=False)
        state = model.state_dict()
        edits = edited_slices(sources, candidate["operations"], commitment["max_edit_elements"])
        for op, values in edits:
            state[op["tensor"]].flatten()[op["start"]:op["start"] + op["count"]].copy_(values)
        result = {**candidate, "selection": score(model, tokenizer, dataset, config)}
        if "guard" in config:
            result["guard"] = score(model, tokenizer, guard_data, guard_config)
            result["guard_passed"] = guard_passes(guard_base, result["guard"], config["guard"])
        results.append(result)
        print(f"candidate {candidate['id']}: selection accuracy={result['selection']['accuracy']:.6f} nll={result['selection']['label_nll']:.6f}", flush=True)
    winner = choose(results, baseline, config["selection_policy"])
    report = {"schema": "nc/candidate-selection/v1", "source_session_sha256": sha(source / "session.json"),
              "selection_sha256": commitment["selection_sha256"], "policy": config["selection_policy"],
              "baseline": baseline, "candidates": results,
              "selected_id": winner["id"] if winner else None,
              "controller_recommended_id": session["selected"]["id"]}
    if "guard" in config:
        report["guard_baseline"] = guard_base
    write(output / "selection-report.json", report)
    if winner is None:
        raise RuntimeError("No candidate passed the precommitted validation-selection rule; final test remains unopened")
    for name in ["transcript.jsonl", "commitment.json"]:
        shutil.copyfile(source / name, output / name)
    edits = edited_slices(sources, winner["operations"], commitment["max_edit_elements"])
    changed = save_candidate(directory / "model/model.safetensors", output / "candidate.safetensors", edits)
    final = copy.deepcopy(session)
    final.update({"controller_recommended": session["selected"], "selected": winner,
                  "changed_parameters": changed, "candidate_sha256": sha(output / "candidate.safetensors"),
                  "selection_report_sha256": sha(output / "selection-report.json")})
    write(output / "session.json", final)
    print(f"Frozen candidate {winner['id']}; final held-out dataset has not been read.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["directory", "source", "output"]:
        parser.add_argument("--" + name, type=pathlib.Path, required=True)
    args = parser.parse_args()
    select(args.directory.resolve(), args.source.resolve(), args.output.resolve())
