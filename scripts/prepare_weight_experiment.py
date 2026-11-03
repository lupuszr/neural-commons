#!/usr/bin/env python3
"""Prepare a fixed, small synthetic sentiment probe, NOT a benchmark claim."""
import argparse
import json
import pathlib
from huggingface_hub import snapshot_download

MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"
REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"

DEVELOPMENT = [
    ("I loved every minute of this movie.", 0), ("The meal was delicious and the service was excellent.", 0),
    ("This book is a wonderful read.", 0), ("The camera takes beautiful pictures.", 0),
    ("The room was clean and comfortable.", 0), ("A fantastic concert with amazing musicians.", 0),
    ("The headphones sound great.", 0), ("The staff were friendly and helpful.", 0),
    ("I am very happy with this purchase.", 0), ("The game is fun and well designed.", 0),
    ("It was not bad at all; I really enjoyed it.", 0), ("Despite the slow start, the ending was brilliant.", 0),
    ("This movie was boring and badly acted.", 1), ("The food was cold and tasted awful.", 1),
    ("A disappointing book full of errors.", 1), ("The camera broke after one day.", 1),
    ("The hotel was dirty and noisy.", 1), ("The concert was a complete waste of money.", 1),
    ("The headphones are uncomfortable and sound terrible.", 1), ("The staff ignored us for an hour.", 1),
    ("I regret buying this product.", 1), ("The game crashes constantly and is frustrating.", 1),
    ("I wanted to like it, but it was not good.", 1), ("Nice packaging cannot hide the terrible quality.", 1),
]
HELDOUT = [
    ("The bakery sells the most delightful pastries.", 0), ("My new bicycle rides smoothly and feels sturdy.", 0),
    ("The museum tour was engaging and informative.", 0), ("This blanket is wonderfully soft and warm.", 0),
    ("Our guide made the whole trip memorable.", 0), ("The app is easy to use and saves me time.", 0),
    ("The shoes fit perfectly and look fantastic.", 0), ("I would gladly recommend this restaurant.", 0),
    ("The play was moving and beautifully performed.", 0), ("Delivery was quick and the item works perfectly.", 0),
    ("The coffee has a rich, pleasant flavor.", 0), ("This course explained everything clearly.", 0),
    ("I expected problems, but the experience was excellent.", 0), ("There is nothing to dislike about this charming cafe.", 0),
    ("Although expensive, the repair was worth every penny.", 0), ("I did not expect to enjoy the show this much.", 0),
    ("The pastries were stale and unpleasant.", 1), ("The bicycle chain fell off on my first ride.", 1),
    ("The tour was disorganized and dull.", 1), ("This blanket scratches my skin and sheds everywhere.", 1),
    ("The guide was rude and ruined our afternoon.", 1), ("The app deletes my work and freezes constantly.", 1),
    ("The shoes fell apart within a week.", 1), ("I would never recommend this restaurant.", 1),
    ("The play was tedious and poorly performed.", 1), ("Delivery took weeks and the item arrived broken.", 1),
    ("The coffee tastes bitter and burnt.", 1), ("This course was confusing and a waste of time.", 1),
    ("I hoped for a great stay, but the hotel let us down.", 1), ("There is nothing enjoyable about this noisy cafe.", 1),
    ("Even at a discount, this repair was not worth it.", 1), ("The beautiful design does not make up for its defects.", 1),
]


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    model = directory / "model"
    snapshot_download(MODEL, revision=REVISION, local_dir=model,
                      allow_patterns=["model.safetensors", "config.json", "tokenizer.json",
                                      "tokenizer_config.json", "special_tokens_map.json", "README.md"])
    files = {
        "config": {"schema": "nc/causal-lm-label-config/v1", "metric": "binary_label_nll/v1",
                   "labels": [" positive", " negative"],
                   "prompt": "Classify the review as positive or negative.\nReview: {text}\nSentiment:",
                   "max_samples": 128, "max_tokens": 256, "batch_size": 8},
        "policy": {"schema": "nc/metric-policy/v1", "metric": "binary_label_nll/v1",
                   "direction": "minimize", "threshold": 0.6931471805599453,
                   "min_improvement": 0.01, "tolerance": 1e-6},
        "source": {"model": MODEL, "revision": REVISION, "license": "Apache-2.0",
                   "task": "Synthetic English sentiment forced-choice probe authored for this experiment",
                   "development_samples": len(DEVELOPMENT), "heldout_samples": len(HELDOUT),
                   "limitations": "Small hand-written split; not an independent benchmark or evidence of general LLM improvement."},
    }
    for name, rows in [("development", DEVELOPMENT), ("heldout", HELDOUT)]:
        files[name] = {"schema": "nc/text-classification/v1", "split": name,
                       "samples": [{"text": text, "label": label} for text, label in rows]}
    for name, value in files.items():
        path = directory / (name + ".json")
        data = json.dumps(value, indent=2) + "\n"
        if path.exists() and path.read_text() != data:
            raise ValueError("refusing to replace an existing experiment definition")
        path.write_text(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=pathlib.Path, required=True)
    prepare(parser.parse_args().directory.resolve())
