#!/usr/bin/env python3
"""Operator-installed evaluator for a real causal LM; consumes only verified files."""
import json
import os
import pathlib
import sys
import tempfile

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
from llm_runtime import guard_passes, load_model, materialize, score


def main():
    request = json.loads(pathlib.Path(sys.argv[1]).read_text())
    config = json.loads(pathlib.Path(request["config"]).read_text())
    dataset = json.loads(pathlib.Path(request["dataset"]).read_text())
    if config["metric"] != request["spec"]["metric"]:
        raise ValueError("metric mismatch")
    if len(dataset["samples"]) > request["spec"]["max_samples"]:
        raise ValueError("sample budget exceeded")
    scores = {}
    metric_key = {"binary_label_nll/v1": "label_nll", "accuracy/v1": "accuracy", "guarded_accuracy/v1": "accuracy"}.get(config["metric"])
    if metric_key is None:
        raise ValueError("unsupported metric")
    guards = {}
    if config["metric"] == "guarded_accuracy/v1" and "guard" not in config:
        raise ValueError("guarded metric requires a guard")
    if "guard" in config and config["metric"] != "guarded_accuracy/v1":
        raise ValueError("a configured guard requires the guarded metric")
    if "guard" in config:
        guard = config["guard"]
        guard_data = json.loads(pathlib.Path(request["inference_artifacts"][guard["dataset_artifact"]]).read_text())
        guard_config = json.loads(pathlib.Path(request["inference_artifacts"][guard["config_artifact"]]).read_text())
    for which in ["base", "candidate"]:
        with tempfile.TemporaryDirectory(prefix="nc-lm-") as directory:
            materialize(directory, request[which + "_files"], request["inference_artifacts"])
            model, tokenizer = load_model(directory, device="cpu")
            scores[which] = score(model, tokenizer, dataset, config)
            if "guard" in config:
                guards[which] = score(model, tokenizer, guard_data, guard_config)
            del model, tokenizer
    guard_ok = True
    if guards:
        guard_ok = guard_passes(guards["base"], guards["candidate"], config["guard"])
        scores["guard"] = {**guards, "passed": guard_ok, "policy": config["guard"]}
    candidate_score = scores["candidate"][metric_key]
    if config["metric"] == "guarded_accuracy/v1" and not guard_ok:
        candidate_score = 0.0
    print(json.dumps({"schema": "nc/evaluator-result/v1", "spec": request["spec_id"],
                      "metric": request["spec"]["metric"],
                      "base": scores["base"][metric_key], "candidate": candidate_score,
                      "backend": request["spec"]["backend"], "details": scores}, allow_nan=False))


if __name__ == "__main__":
    main()
