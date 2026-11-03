#!/usr/bin/env python3
"""Reconstruct a recorded agent edit without calling a controller or using labels.

Works with public transcripts whose review text has been redacted: the numerical
operations and recorded activation vector are sufficient to reproduce the bytes.
"""
import argparse
import json
import pathlib

import torch
from weight_agent import edited_slices, load_file, save_candidate, sha


def replay(session_path, base, output):
    session = json.loads(session_path.read_text())
    if output.exists():
        raise ValueError("output already exists")
    if sha(base) != session["commitment"]["target_sha256"]:
        raise ValueError("base checkpoint hash mismatch")
    original = load_file(base)
    features = {name: torch.tensor(values, dtype=torch.float32)
                for name, values in session.get("feature_vectors", {}).items()}
    if set(features) & set(original):
        raise ValueError("feature source collides with checkpoint tensor")
    operations = session["selected"]["operations"]
    if any(op["tensor"] not in original for op in operations):
        raise ValueError("destination is not a checkpoint tensor")
    edits = edited_slices({**original, **features}, operations, session["commitment"]["max_edit_elements"])
    changed = save_candidate(base, output, edits)
    actual = sha(output)
    if actual != session["candidate_sha256"] or changed != session["changed_parameters"]:
        raise ValueError("replayed checkpoint differs from the recorded candidate")
    return {"checkpoint_sha256": actual, "changed_parameters": changed, "exact_match": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["session", "base", "output"]:
        parser.add_argument("--" + name, type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.session, args.base, args.output), indent=2))
