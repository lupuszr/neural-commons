#!/usr/bin/env python3
"""AG News task with a precommitted sentiment-preservation guard."""
import argparse
import hashlib
import json
import pathlib
import random
import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download
from transformers import AutoTokenizer
from prepare_weight_experiment import DEVELOPMENT, HELDOUT

DATASET = "fancyzhx/ag_news"
REVISION = "eb185aade064a813bc0b7f42de02595523103ca4"


def prepare(directory, model):
    expected = next(f.lfs.sha256 for f in HfApi().model_info("HuggingFaceTB/SmolLM2-135M-Instruct",
                    revision="12fd25f77366fa6b3b4b768ec3050bf629380bac", files_metadata=True).siblings
                    if f.rfilename == "model.safetensors")
    h = hashlib.sha256()
    with (model / "model.safetensors").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    if h.hexdigest() != expected:
        raise ValueError("expected the unmodified pinned model")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "model").symlink_to(model.resolve(), target_is_directory=True)
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    prompt = "Classify the news as World, Sports, Business, or Technology.\nNews: {text}\nCategory:"
    labels = [" World", " Sports", " Business", " Technology"]
    ids = [tokenizer.encode(label, add_special_tokens=False) for label in labels]
    assert all(len(row) == 1 for row in ids)
    sources, groups = {}, {}
    for split in ["train", "test"]:
        path = pathlib.Path(hf_hub_download(DATASET, f"data/{split}-00000-of-00001.parquet", repo_type="dataset", revision=REVISION))
        sources[split] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = pq.read_table(path).to_pylist()
        buckets = [[] for _ in labels]
        for index, row in enumerate(rows):
            buckets[row["label"]].append({"id": f"ag_news/{split}/{index}", "text": row["text"], "label": row["label"]})
        rng = random.Random(20261105 if split == "train" else 20261106)
        groups[split] = []
        for bucket in buckets:
            rng.shuffle(bucket)
            eligible, seen = [], set()
            for row in bucket:
                if row["text"] in seen:
                    continue
                seen.add(row["text"])
                if len(tokenizer.encode(prompt.format(text=row["text"]), add_special_tokens=True)) <= 220:
                    eligible.append(row)
                if len(eligible) == (96 if split == "train" else 250):
                    break
            assert len(eligible) == (96 if split == "train" else 250)
            groups[split].append(eligible)
    samples = {"development": sum((g[:32] for g in groups["train"]), []),
               "selection": sum((g[32:96] for g in groups["train"]), []),
               "heldout": sum(groups["test"], [])}
    for name, rows in samples.items():
        random.Random(20261107).shuffle(rows)
    dimension = json.loads((model / "config.json").read_text())["hidden_size"]
    files = {name: {"schema": "nc/text-classification/v1", "split": name, "samples": rows} for name, rows in samples.items()}
    files["guard"] = {"schema": "nc/text-classification/v1", "split": "previously-exposed-regression-guard",
                       "samples": [{"id": f"synthetic-sentiment/{i}", "text": text, "label": label}
                                   for i, (text, label) in enumerate(DEVELOPMENT + HELDOUT)]}
    files["guard-config"] = {"labels": [" positive", " negative"],
                             "prompt": "Classify the review as positive or negative.\nReview: {text}\nSentiment:",
                             "max_samples": 128, "max_tokens": 256, "batch_size": 8, "output_text": False}
    files["config"] = {"schema": "nc/causal-lm-label-config/v1", "metric": "guarded_accuracy/v1", "labels": labels,
                       "prompt": prompt, "max_samples": 1024, "max_tokens": 256, "batch_size": 8, "output_text": False,
                       "agent_objective": "Improve four-class news topic accuracy, with lower label NLL as secondary goal. Only the four task-label embedding rows may be edited. Existing sentiment classification must be preserved by an independent guard. You may use development activation contrasts, including one class versus all others (negative_label=-1). Do not change prompts, data, architecture or other weights.",
                       "edit_scope": [{"tensor": "model.embed_tokens.weight", "start": row[0] * dimension, "count": dimension} for row in ids],
                       "guard": {"dataset_artifact": "guard_dataset", "config_artifact": "guard_config", "max_accuracy_drop": 0.0, "max_nll_increase": 1e-6},
                       "selection_policy": {"min_accuracy_improvement": 0.01, "max_nll_regression": 0.0,
                                            "rank": ["accuracy_descending", "nll_ascending", "candidate_id_ascending"]}}
    files["policy"] = {"schema": "nc/metric-policy/v1", "metric": "guarded_accuracy/v1", "direction": "maximize",
                       "threshold": 0.70, "min_improvement": 0.02, "tolerance": 1e-8}
    files["source"] = {"model": "HuggingFaceTB/SmolLM2-135M-Instruct", "revision": "12fd25f77366fa6b3b4b768ec3050bf629380bac",
                       "model_sha256": expected, "license": "Apache-2.0 (model)", "dataset": DATASET, "dataset_revision": REVISION,
                       "dataset_url": "https://huggingface.co/datasets/fancyzhx/ag_news", "dataset_file_sha256": sources,
                       "split_seeds": [20261105, 20261106, 20261107], "development_samples": 128, "selection_samples": 256,
                       "heldout_samples": 1000, "guard_samples": 56,
                       "split_method": "Per-class fixed-seed shuffle; exact text deduplication within class; prompt length <=220 tokens; first 32/class train for development, next 64/class for selection, first 250/class test for final. No model scores used for filtering.",
                       "limitations": "Forced-choice classification on a fixed length-filtered test subset; no claim of general generation improvement. Public benchmark pretraining contamination cannot be excluded. Guard is previously exposed and is not an independent benchmark."}
    for name, value in files.items():
        (directory / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=pathlib.Path, required=True)
    p.add_argument("--model", type=pathlib.Path, required=True)
    a = p.parse_args()
    prepare(a.directory.resolve(), a.model.resolve())
