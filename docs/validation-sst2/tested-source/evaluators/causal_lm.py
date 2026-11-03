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
from llm_runtime import load_model, materialize, score


def main():
    request = json.loads(pathlib.Path(sys.argv[1]).read_text())
    config = json.loads(pathlib.Path(request["config"]).read_text())
    dataset = json.loads(pathlib.Path(request["dataset"]).read_text())
    if config["metric"] != request["spec"]["metric"]:
        raise ValueError("metric mismatch")
    if len(dataset["samples"]) > request["spec"]["max_samples"]:
        raise ValueError("sample budget exceeded")
    scores = {}
    metric_key = {"binary_label_nll/v1": "label_nll", "accuracy/v1": "accuracy"}.get(config["metric"])
    if metric_key is None:
        raise ValueError("unsupported metric")
    for which in ["base", "candidate"]:
        with tempfile.TemporaryDirectory(prefix="nc-lm-") as directory:
            materialize(directory, request[which + "_files"], request["inference_artifacts"])
            model, tokenizer = load_model(directory, device="cpu")
            scores[which] = score(model, tokenizer, dataset, config)
            del model, tokenizer
    print(json.dumps({"schema": "nc/evaluator-result/v1", "spec": request["spec_id"],
                      "metric": request["spec"]["metric"],
                      "base": scores["base"][metric_key], "candidate": scores["candidate"][metric_key],
                      "backend": request["spec"]["backend"], "details": scores}, allow_nan=False))


if __name__ == "__main__":
    main()
