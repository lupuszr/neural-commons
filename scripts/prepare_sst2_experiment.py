#!/usr/bin/env python3
"""Fixed development/selection splits from SST-2 train; official validation is final.

No model scores are used to choose examples. Original dataset indices and file
hashes make the split reproducible without redistributing the full review corpus.
"""
import argparse
import hashlib
import json
import pathlib
import random

import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download

DATASET = "stanfordnlp/sst2"
REVISION = "8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb"


def prepare(directory, model):
    metadata = HfApi().model_info("HuggingFaceTB/SmolLM2-135M-Instruct",
                                revision="12fd25f77366fa6b3b4b768ec3050bf629380bac", files_metadata=True)
    expected = next(f.lfs.sha256 for f in metadata.siblings if f.rfilename == "model.safetensors")
    actual = hashlib.sha256()
    with (model / "model.safetensors").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            actual.update(block)
    if actual.hexdigest() != expected:
        raise ValueError("model must be the unmodified pinned SmolLM2 checkpoint")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "model").symlink_to(model.resolve(), target_is_directory=True)
    sources, raw = {}, {}
    for split in ["train", "validation"]:
        path = pathlib.Path(hf_hub_download(DATASET, f"data/{split}-00000-of-00001.parquet",
                            repo_type="dataset", revision=REVISION))
        sources[split] = hashlib.sha256(path.read_bytes()).hexdigest()
        raw[split] = pq.read_table(path).to_pylist()
    rng = random.Random(20261104)
    groups = [[], []]
    seen = set()
    for row in raw["train"]:
        text = row["sentence"].strip()
        if text in seen or not 8 <= len(text.split()) <= 50:
            continue
        seen.add(text)
        groups[row["label"]].append(row)
    for group in groups:
        rng.shuffle(group)
    partitions = {"development": groups[0][:64] + groups[1][:64],
                  "selection": groups[0][64:192] + groups[1][64:192],
                  "heldout": raw["validation"]}
    for name in ["development", "selection"]:
        rng.shuffle(partitions[name])
    files = {}
    for name, rows in partitions.items():
        files[name] = {"schema": "nc/text-classification/v1", "split": name,
                       "samples": [{"id": f"sst2/{'validation' if name == 'heldout' else 'train'}/{r['idx']}",
                                    "text": r["sentence"].strip(), "label": 1 - r["label"]} for r in rows]}
    assert not ({r["id"] for r in files["development"]["samples"]} &
                {r["id"] for r in files["selection"]["samples"]})
    files["config"] = {"schema": "nc/causal-lm-label-config/v1", "metric": "accuracy/v1",
                       "labels": [" positive", " negative"],
                       "prompt": "Classify the review as positive or negative.\nReview: {text}\nSentiment:",
                       "max_samples": 1024, "max_tokens": 256, "batch_size": 8,
                       "output_text": False,
                       "agent_objective": "Improve classification accuracy first; improve label NLL as a secondary goal. Pure final-norm scaling cannot change argmax accuracy. Seek selective weight edits that correct mistakes. Validation and final-test labels are unavailable to the controller.",
                       "selection_policy": {"min_accuracy_improvement": 0.01, "max_nll_regression": 0.0,
                                            "rank": ["accuracy_descending", "nll_ascending", "candidate_id_ascending"]}}
    files["policy"] = {"schema": "nc/metric-policy/v1", "metric": "accuracy/v1", "direction": "maximize",
                       "threshold": 0.70, "min_improvement": 0.02, "tolerance": 1e-8}
    files["source"] = {"model": "HuggingFaceTB/SmolLM2-135M-Instruct",
                       "revision": "12fd25f77366fa6b3b4b768ec3050bf629380bac", "license": "Apache-2.0 (model)",
                       "dataset": DATASET, "dataset_revision": REVISION, "dataset_url": "https://huggingface.co/datasets/stanfordnlp/sst2",
                       "dataset_file_sha256": sources, "split_seed": 20261104,
                       "development_samples": 128, "selection_samples": 256, "heldout_samples": 872,
                       "split_method": "Deduplicated train texts of 8..50 whitespace words; shuffle each class with fixed seed; 64/class development, next 128/class selection. All official validation examples reserved for final evaluation.",
                       "limitations": "Forced-choice sentiment, not free generation. Public dataset may have appeared in pretraining. Official validation serves as our final holdout, not the hidden GLUE test set. Train-derived selection can include related phrases."}
    for name, value in files.items():
        (directory / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=pathlib.Path, required=True)
    parser.add_argument("--model", type=pathlib.Path, required=True)
    args = parser.parse_args()
    prepare(args.directory.resolve(), args.model)
