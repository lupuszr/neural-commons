"""Replaceable Transformers adapter. No training or remote model code execution."""
import json
import math
import pathlib
import hashlib

import torch
from safetensors.torch import load_file
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer


def load_model(directory, device="cpu"):
    torch.set_num_threads(4)
    torch.manual_seed(17)
    torch.set_grad_enabled(False)
    model = AutoModelForCausalLM.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False,
        torch_dtype=torch.float32, attn_implementation="eager",
    ).eval().to(device)
    model.requires_grad_(False)
    tokenizer = AutoTokenizer.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False,
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    return model, tokenizer


@torch.inference_mode()
def score(model, tokenizer, dataset, config):
    """Forced choice among single-token labels; also record calibrated label NLL.

    This is a narrow classification probe, not free-form instruction following.
    """
    rows = dataset["samples"]
    if not rows or len(rows) > config["max_samples"]:
        raise ValueError("invalid sample count")
    labels = config["labels"]
    token_ids = [tokenizer.encode(label, add_special_tokens=False) for label in labels]
    if any(len(ids) != 1 for ids in token_ids):
        raise ValueError("this adapter requires single-token labels")
    predictions = []
    device = next(model.parameters()).device
    for start in range(0, len(rows), config["batch_size"]):
        batch = rows[start:start + config["batch_size"]]
        prompts = [config["prompt"].format(text=row["text"]) for row in batch]
        encoded = tokenizer(prompts, padding=True, return_tensors="pt")
        if encoded["input_ids"].shape[1] > config["max_tokens"]:
            raise ValueError("prompt exceeds token policy")
        logits = model(**encoded.to(device)).logits[:, -1, :].float().cpu()
        selected = logits[:, [ids[0] for ids in token_ids]]
        log_probs = selected.log_softmax(-1)
        for row, probabilities, raw in zip(batch, log_probs, selected):
            label = row["label"]
            if not isinstance(label, int) or not 0 <= label < len(labels):
                raise ValueError("invalid label")
            identity = {"text": row["text"]} if config.get("output_text", True) else {
                "id": row.get("id"), "text_sha256": hashlib.sha256(row["text"].encode()).hexdigest()}
            predictions.append({**identity, "label": label,
                                "prediction": int(probabilities.argmax()),
                                "nll": -float(probabilities[label]),
                                "label_logits": raw.tolist()})
    loss = sum(p["nll"] for p in predictions) / len(predictions)
    if not math.isfinite(loss):
        raise ValueError("nonfinite score")
    return {"accuracy": sum(p["label"] == p["prediction"] for p in predictions) / len(predictions),
            "label_nll": loss, "samples": len(predictions), "predictions": predictions}


def materialize(directory, files, inference):
    """Link already verified immutable artifacts into a private model directory."""
    directory = pathlib.Path(directory)
    allowed = {"model_config": "config.json", "tokenizer": "tokenizer.json",
               "tokenizer_config": "tokenizer_config.json", "special_tokens": "special_tokens_map.json"}
    for name, filename in allowed.items():
        if name in inference:
            (directory / filename).symlink_to(pathlib.Path(inference[name]).resolve())
    for name, path in files.items():
        name = name or "model.safetensors"
        if pathlib.Path(name).name != name or name in {".", ".."}:
            raise ValueError("unsafe checkpoint filename")
        (directory / name).symlink_to(pathlib.Path(path).resolve())
    if list(files) != [""]:
        weight_map = {}
        from safetensors import safe_open
        for name, path in files.items():
            with safe_open(path, framework="pt", device="cpu") as handle:
                for tensor in handle.keys():
                    if tensor in weight_map:
                        raise ValueError("duplicate tensor across shards")
                    weight_map[tensor] = name
        (directory / "model.safetensors.index.json").write_text(json.dumps({"metadata": {}, "weight_map": weight_map}))


@torch.inference_mode()
def activation_contrast(model, tokenizer, dataset, config, positive, negative):
    """Read-only difference of final hidden-state class means on development data.

    No fitted optimizer, gradient or held-out input. The controller decides whether
    and how to use this supervised statistic in an actual weight edit.
    """
    rows = dataset["samples"]
    groups = {positive: [], negative: []}
    if positive == negative or any(label not in range(len(config["labels"])) for label in groups):
        raise ValueError("invalid contrast labels")
    device = next(model.parameters()).device
    for start in range(0, len(rows), config["batch_size"]):
        batch = rows[start:start + config["batch_size"]]
        encoded = tokenizer([config["prompt"].format(text=r["text"]) for r in batch], padding=True, return_tensors="pt")
        if encoded["input_ids"].shape[1] > config["max_tokens"]:
            raise ValueError("prompt exceeds token budget")
        states = model(**encoded.to(device), output_hidden_states=True).hidden_states[-1][:, -1, :].float().cpu()
        for row, state in zip(batch, states):
            if row["label"] in groups:
                groups[row["label"]].append(state.clone())
    if any(not group for group in groups.values()):
        raise ValueError("empty contrast class")
    groups = {label: torch.stack(values) for label, values in groups.items()}
    vector = groups[positive].mean(0) - groups[negative].mean(0)
    vector /= vector.norm().clamp_min(1e-12)
    projections = {str(label): {"mean": float((states @ vector).mean()),
                               "std": float((states @ vector).std(unbiased=False)), "samples": len(states)}
                   for label, states in groups.items()}
    return vector, projections
