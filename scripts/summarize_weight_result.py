#!/usr/bin/env python3
"""Paired descriptive statistics from an immutable external-evaluator output."""
import argparse
import json
import math
import pathlib


def summarize(output):
    base, candidate = output["details"]["base"], output["details"]["candidate"]
    if len(base["predictions"]) != len(candidate["predictions"]):
        raise ValueError("different sample counts")
    corrected = regressed = 0
    for before, after in zip(base["predictions"], candidate["predictions"]):
        if (before.get("id"), before.get("text_sha256"), before.get("text"), before["label"]) != (
                after.get("id"), after.get("text_sha256"), after.get("text"), after["label"]):
            raise ValueError("unaligned paired predictions")
        old, new = before["prediction"] == before["label"], after["prediction"] == after["label"]
        corrected += not old and new
        regressed += old and not new
    n, discordant = base["samples"], corrected + regressed
    delta = (corrected - regressed) / n
    variance = (discordant - n * delta * delta) / (n - 1) if n > 1 else 0
    se = math.sqrt(variance / n)
    p = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(corrected, regressed) + 1)) / 2**discordant) if discordant else 1.0
    result = {"samples": n, "base_accuracy": base["accuracy"], "candidate_accuracy": candidate["accuracy"],
            "base_label_nll": base["label_nll"], "candidate_label_nll": candidate["label_nll"],
            "corrected": corrected, "regressed": regressed, "accuracy_difference": delta,
            "paired_normal_95pct_interval": [delta - 1.96 * se, delta + 1.96 * se],
            "mcnemar_exact_two_sided_p": p,
            "scope": "Single fixed public task; interval does not account for pretraining contamination or task selection."}
    if all("nll" in row for row in base["predictions"] + candidate["predictions"]):
        changes = [old["nll"] - new["nll"] for old, new in zip(base["predictions"], candidate["predictions"])]
        mean = sum(changes) / n
        error = math.sqrt(sum((v - mean)**2 for v in changes) / (n - 1) / n) if n > 1 else 0
        result["nll_reduction"] = mean
        result["paired_nll_reduction_normal_95pct_interval"] = [mean - 1.96 * error, mean + 1.96 * error]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()
    print(json.dumps(summarize(json.loads(args.output.read_text())), indent=2))
