#!/usr/bin/env python3
"""A bounded LLM controller that directly edits another model's weight values.

Controller backends: OpenAI Responses API and authenticated Codex CLI. Neither
backend receives held-out examples. All numeric operations execute in this host,
not in model-generated Python/shell. Every candidate starts from the pristine base.
"""
import argparse
import hashlib
import json
import math
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from continuation_job import lease_fds

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluators"))
from llm_runtime import activation_contrast, load_model, score
import torch
from safetensors.torch import load_file


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


ACTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"actions": {"type": "array", "minItems": 1, "maxItems": 4,
        "items": {"type": "object", "additionalProperties": False,
            "properties": {"tool": {"type": "string", "enum": ["inspect", "inspect_diff", "tokenize", "contrast", "experiment", "finish"]},
                           "arguments": {"type": "string", "description": "JSON encoded tool arguments"}},
            "required": ["tool", "arguments"]}}}, "required": ["actions"],
}

INSTRUCTIONS = """You are the weight-space controller in Neural Commons. Improve a
different, frozen pretrained causal language model on the supplied development
task by directly editing its numerical weights. You are not a coding assistant.
Do not use shell, filesystem, browser, plugins or any native tools. Return only
the requested JSON actions; the host executes the tools described below.
No gradients, optimizer, extra training examples or held-out access are available.
Do not claim broad capability improvement. Choose a non-empty candidate if a
plausible one exists, but report failures honestly. Follow task.agent_objective
when provided; otherwise optimize label NLL while retaining accuracy. Follow
task.user_instructions when supplied. task.edit_scope, if present, contains the
only editable regions selected by the user. Without it, you may choose any model
tensor; do not infer a restriction to embeddings or inherit a previous agent's
scope. Respect the current task's explicit execution budgets. Pure global
logit scaling cannot improve argmax classification accuracy. You must inspect relevant weights before
editing, and explain a causal hypothesis for each experiment.

Tools (arguments is a JSON-encoded object):
inspect: {"tensor":name,"start":integer,"count":integer}. Returns a flat slice
of at most 256 original values, shape, dtype, mean, standard deviation and norm.
inspect_diff: {"tensor":name,"start":integer,"count":integer}. When an inherited
experiment is supplied, reads exact changed indices and before/after/delta values
from the previous controller's patch (at most 256 element positions). The current
BASE is already that controller's improved checkpoint. Inspect its diff before
proposing a further edit. Previous operations describe how BASE was created; do not
blindly apply them again. Your new edits are relative to BASE, not its ancestor.
tokenize: {"text":string}. Returns token IDs to identify embedding/output rows.
contrast: {"positive_label":integer,"negative_label":integer}. Returns a named
source vector: the unit-normalized difference of BASE final-hidden-state means
for those development classes, and class projection statistics. Use negative_label=-1
for the chosen class versus all other classes. No gradients are
used. You may use this vector as add_tensor in a numeric edit, choosing the scale
yourself. It is a supervised development statistic, not a learned optimizer or a
new checkpoint tensor. Consider selective output-row edits using this direction
if existing token semantics do not separate the classes sufficiently.
experiment: {"hypothesis":string,"operations":[{"tensor":name,"start":integer,
"count":integer,"scale":number,"add_tensor":name_or_null,"add_start":integer,
"add_scale":number}]}. For each disjoint destination slice, replaces BASE values
with BASE_destination * scale + BASE_source * add_scale (omit source using null).
All slices use flattened row-major element indices. The source and destination
have count elements; source is always from pristine base. Values are rounded to
the original stored dtype before inference. Every experiment starts from base,
not the previous experiment. You can edit any named tensor, including an entire
norm vector, specific MLP columns via individual slices, or embedding/output rows.
The target may tie output head and input embeddings: inspect model configuration.
No fixed winning patch is supplied. Tool returns development metrics and errors.
finish: {"candidate":integer,"reason":string}. Select a tested candidate ID.
Use the budgets supplied below. Do not try to read hidden evaluation data. A final
candidate is frozen before a separate evaluator sees any held-out examples.
"""


class ControllerUnavailable(RuntimeError):
    pass


def controller_history(history):
    """Keep full observations in the audit log, bound repeated old observations.

    Baseline and the two newest probes retain every development prediction.
    Older probes retain metrics, hypotheses/operations, a confusion matrix and
    eight high-loss errors. No selection or final-test input is introduced.
    """
    import copy
    result = copy.deepcopy(history)
    probes = [e for e in result if e.get('action', {}).get('tool') == 'experiment'
              and 'predictions' in e.get('result', {})]
    for entry in probes[:-2]:
        rows = entry['result'].pop('predictions')
        confusion = {}
        for row in rows:
            key = str(row['label']) + '->' + str(row['prediction'])
            confusion[key] = confusion.get(key, 0) + 1
        entry['result']['confusion'] = confusion
        entry['result']['highest_loss_errors'] = sorted(
            (r for r in rows if r['label'] != r['prediction']), key=lambda r: -r['nll'])[:8]
        entry['result']['older_prediction_detail'] = 'summarized; complete result retained in transcript'
    return result


def restore_transcript(rows, commitment):
    """Restore a completed action boundary without resetting attempts or context."""
    original = rows[0]['commitment']
    if {k:v for k,v in original.items() if k != 'implementation_sha256'} != {
            k:v for k,v in commitment.items() if k != 'implementation_sha256'}:
        raise ValueError('resume commitment mismatch: inputs, model and budgets must remain fixed')
    history = [{'initial':rows[0]['initial']}]
    candidates, inspected, features = [], set(), {}
    probes, selected, diff_inspected, last_round = 0, None, False, -1
    pending = []
    for row in rows[1:]:
        if 'round' in row:
            if pending:
                raise ValueError('unfinished action batch before next controller round')
            last_round = row['round'];pending = list(row['decision']['actions'])
        elif 'action' in row:
            if not pending or row['action'] != pending.pop(0):
                raise ValueError('transcript action does not match recorded decision')
            history.append(row)
            tool, kw, value = row['action']['tool'], json.loads(row['action']['arguments']), row['result']
            if tool == 'experiment' and probes < commitment['max_probes']:
                probes += 1
            if 'error' in value:
                continue
            if tool == 'inspect':inspected.add(kw['tensor'])
            elif tool == 'inspect_diff':diff_inspected |= bool(value['changes'])
            elif tool == 'contrast':features[value['source_tensor']] = torch.tensor(value['values'],dtype=torch.float32)
            elif tool == 'experiment':
                if value['candidate'] != len(candidates):raise ValueError('candidate ID sequence changed')
                candidates.append({'id':value['candidate'],'hypothesis':kw['hypothesis'],
                                   'operations':kw['operations'],'development':value})
            elif tool == 'finish':selected=value['frozen_candidate'];pending=[]
    return original, history, candidates, inspected, features, probes, selected, diff_inspected, last_round, pending


class Controller:
    def __init__(self, backend, model, timeout=180):
        self.backend, self.model, self.timeout = backend, model, timeout

    def next(self, history):
        prompt = INSTRUCTIONS + "\n\nExperiment history:\n" + json.dumps(controller_history(history), allow_nan=False)
        if self.backend == "codex":
            with tempfile.TemporaryDirectory(prefix="nc-controller-") as d:
                directory = pathlib.Path(d)
                schema, output = directory / "schema.json", directory / "decision.json"
                write(schema, ACTION_SCHEMA)
                command = ["codex", "exec", "--ignore-user-config", "--ignore-rules",
                           "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
                           "--model", self.model, "--cd", d, "--json", "--color", "never",
                           "--output-schema", str(schema), "--output-last-message", str(output),
                           "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
                           "-c", 'project_doc_max_bytes=0', "-c", 'model_reasoning_effort="medium"']
                for feature in ["shell_tool", "unified_exec", "apps", "remote_plugin", "browser_use",
                                "computer_use", "multi_agent", "code_mode_host", "view_image", "hooks"]:
                    command += ["-c", f"features.{feature}=false"]
                command += ["-c", "features.skip_host_skill_discovery=true", "-"]
                env = os.environ.copy()
                env.pop("OPENAI_API_KEY", None)  # use Codex's existing login, not a stale API key
                result = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                        timeout=self.timeout, env=env, pass_fds=lease_fds())
                if result.returncode or not output.is_file():
                    # Classify without echoing provider text or credential fragments.
                    diagnostic = (result.stdout + result.stderr).lower()
                    markers = [s for s in ['context', 'rate limit', 'usage limit', 'quota',
                                           'unauthorized', 'timeout', 'reconnecting', 'network'] if s in diagnostic]
                    raise ControllerUnavailable(f"Codex controller failed ({result.returncode}); diagnostic categories: {markers}")
                events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
                for event in events:
                    item = event.get("item", {})
                    if item.get("type") in {"command_execution", "mcp_tool_call", "web_search", "file_change"}:
                        raise RuntimeError("Codex attempted a native tool; controller isolation failed")
                decision = json.loads(output.read_text())
                usage = [e for e in events if e.get("type") == "turn.completed"]
                return decision, {"backend": "codex", "model_requested": self.model,
                                  "usage": usage, "native_tool_calls": 0}
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for backend=openai")
        body = {"model": self.model, "input": [{"role": "user", "content": prompt}],
                "store": False, "max_output_tokens": 8192,
                "text": {"format": {"type": "json_schema", "name": "weight_actions",
                                      "strict": True, "schema": ACTION_SCHEMA}}}
        request = urllib.request.Request("https://api.openai.com/v1/responses",
                    data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + key,
                    "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as error:
            # Do not echo server errors: they can contain credential fragments.
            raise RuntimeError(f"OpenAI controller HTTP {error.code}") from None
        if data.get("status") != "completed":
            raise RuntimeError("OpenAI response did not complete")
        text = "".join(c.get("text", "") for item in data["output"] if item["type"] == "message"
                       for c in item["content"] if c["type"] == "output_text")
        return json.loads(text), {"backend": "openai", "model": data["model"],
                                 "response_id": data["id"], "usage": data.get("usage")}


def validate_operations(original, operations, max_elements):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 256:
        raise ValueError("expected 1..256 operations")
    spans, total = {}, 0
    for op in operations:
        if set(op) != {"tensor", "start", "count", "scale", "add_tensor", "add_start", "add_scale"}:
            raise ValueError("unexpected operation fields")
        name, start, count = op["tensor"], op["start"], op["count"]
        if name not in original or type(start) is not int or type(count) is not int:
            raise ValueError("unknown tensor or noninteger range")
        if start < 0 or count <= 0 or start + count > original[name].numel():
            raise ValueError("destination out of bounds")
        if any(start < end and start + count > begin for begin, end in spans.get(name, [])):
            raise ValueError("overlapping edits")
        spans.setdefault(name, []).append((start, start + count))
        total += count
        if total > max_elements:
            raise ValueError("edit element budget exceeded")
        if not all(type(op[k]) in (int, float) and math.isfinite(op[k]) and abs(op[k]) <= 100 for k in ["scale", "add_scale"]):
            raise ValueError("invalid coefficient")
        source, offset = op["add_tensor"], op["add_start"]
        if type(offset) is not int or offset < 0:
            raise ValueError("invalid source range")
        if source is not None and (source not in original or offset + count > original[source].numel()):
            raise ValueError("source out of bounds")
        if source is None and op["add_scale"] != 0:
            raise ValueError("nonzero addition requires a source")


@torch.inference_mode()
def edited_slices(original, operations, max_elements):
    validate_operations(original, operations, max_elements)
    edits = []
    for op in operations:
        base = original[op["tensor"]].flatten()[op["start"]:op["start"] + op["count"]]
        values = base.float() * op["scale"]
        if op["add_tensor"] is not None:
            source = original[op["add_tensor"]].flatten()[op["add_start"]:op["add_start"] + op["count"]]
            values += source.float() * op["add_scale"]
        values = values.to(base.dtype)
        if not torch.isfinite(values).all():
            raise ValueError("nonfinite edited weights")
        edits.append((op, values))
    if not any(torch.count_nonzero(original[op["tensor"]].flatten()[op["start"]:op["start"] + op["count"]] != values) for op, values in edits):
        raise ValueError("empty numerical edit")
    return edits


def save_candidate(base_file, output, edits):
    # Preserve the exact Safetensors header, offsets, metadata and untouched bytes.
    with open(base_file, "rb") as file:
        length = struct.unpack("<Q", file.read(8))[0]
        header = json.loads(file.read(length))
    shutil.copyfile(base_file, output)
    changed = 0
    with open(output, "r+b") as file:
        for op, values in edits:
            offset = 8 + length + header[op["tensor"]]["data_offsets"][0] + op["start"] * values.element_size()
            file.seek(offset)
            payload = values.contiguous().view(torch.uint8).numpy().tobytes()
            previous = file.read(len(payload))
            width = values.element_size()
            changed += sum(previous[i:i + width] != payload[i:i + width] for i in range(0, len(payload), width))
            file.seek(offset)
            file.write(payload)
    return changed


def validate_edit_scope(config, operations):
    if 'edit_scope' in config and not all(any(
            op['tensor'] == region['tensor'] and op['start'] >= region['start'] and
            op['start'] + op['count'] <= region['start'] + region['count']
            for region in config['edit_scope']) for op in operations):
        raise ValueError('edit exceeds the operator-approved tensor regions')


def run(args):
    if args.resume:
        if (args.output / 'session.json').exists():
            raise ValueError('a finalized session cannot be resumed')
    else:
        args.output.mkdir(parents=True, exist_ok=False)
    config = json.loads(args.config.read_text())
    development = json.loads(args.development.read_text())
    # Only a precomputed hash of the held-out data enters this process.
    commitment = {"schema": "nc/agent-commitment/v1", "target_sha256": sha(args.model / "model.safetensors"),
                  "config_sha256": sha(args.config), "development_sha256": sha(args.development),
                  "heldout_sha256": args.heldout_sha256, "policy_sha256": args.policy_sha256,
                  "backend": args.backend, "controller": args.controller_model,
                  "max_rounds": args.max_rounds, "max_probes": args.max_probes,
                  "max_edit_elements": args.max_edit_elements, "device": "cpu",
                  "model_source": json.loads(args.source.read_text())}
    commitment["min_probes"] = args.min_probes
    if "guard" in config:
        commitment["guard_sha256"] = sha(args.config.parent / "guard.json")
        commitment["guard_config_sha256"] = sha(args.config.parent / "guard-config.json")
    if args.selection_sha256:
        commitment["selection_sha256"] = args.selection_sha256
    commitment["inference_file_sha256"] = {p.name: sha(p) for p in args.model.glob("*.json")}
    commitment["implementation_sha256"] = {name: sha(ROOT / name) for name in
        ["scripts/weight_agent.py", "evaluators/llm_runtime.py"]}
    handoff, parent_diff = None, None
    if args.handoff:
        from weight_handoff import load
        handoff, parent_diff = load(args.handoff.parent, commitment["target_sha256"])
        commitment["handoff_sha256"] = sha(args.handoff)
        commitment["parent_diff_sha256"] = sha(args.handoff.parent / "parent-diff.json")
        commitment["parent_checkpoint"] = handoff["candidate_checkpoint"]
        commitment["parent_proposal"] = handoff["proposal"]
        commitment["implementation_sha256"]["scripts/weight_handoff.py"] = sha(ROOT / "scripts/weight_handoff.py")
    restored = None
    if args.resume:
        rows = [json.loads(line) for line in (args.output / 'transcript.jsonl').read_text().splitlines()]
        restored = restore_transcript(rows, commitment)
        if json.loads((args.output / 'commitment.json').read_text()) != restored[0]:
            raise ValueError('stored commitment differs from the original transcript')
    else:
        write(args.output / "commitment.json", commitment)
    model, tokenizer = load_model(args.model, device="cpu")
    original = load_file(args.model / "model.safetensors")
    edit_limit = args.max_edit_elements if args.max_edit_elements is not None else sum(t.numel() for t in original.values())
    # Text is available to the controller only for the development split.
    development_config = {**config, "output_text": True}
    baseline = restored[1][0]['initial']['baseline'] if restored else score(model, tokenizer, development, development_config)
    inventory = {name: {"shape": list(t.shape), "dtype": str(t.dtype)} for name, t in original.items()}
    history = [{"initial": {"task": config, "model_config": json.loads((args.model / "config.json").read_text()),
                            "inventory": inventory, "baseline": baseline,
                            "budgets": {"rounds": args.max_rounds, "probes": args.max_probes,
                                        "minimum_attempts_before_finish": args.min_probes,
                                        "edit_elements_per_candidate": edit_limit}}}]
    candidates, inspected, probes, selected, features = [], set(), 0, None, {}
    if handoff:
        history[0]["initial"]["inherited_experiment"] = {k:v for k,v in handoff.items()
            if k not in ["evidence_ids", "inference_artifacts"]}
    diff_inspected = False
    controller = Controller(args.backend, args.controller_model, args.controller_timeout)
    def log(event):
        with open(args.output / "transcript.jsonl", "a") as f:
            f.write(json.dumps(event, allow_nan=False) + "\n")
    start_round, pending = 0, []
    if restored:
        resume_evidence = {'transcript_prefix_sha256':sha(args.output / 'transcript.jsonl'),
                           'implementation_sha256':commitment['implementation_sha256'],
                           'context_policy':'baseline-and-two-latest-full/v1'}
        commitment, history, candidates, inspected, features, probes, selected, diff_inspected, last_round, pending = restored
        log({'resume':resume_evidence})
        start_round = last_round if pending else last_round + 1
        print(f'Resuming after {probes} attempts with unchanged inputs and budgets', flush=True)
    else:
        log({"commitment": commitment, **history[0], 'context_policy':'baseline-and-two-latest-full/v1'})
    for round_number in range(start_round, args.max_rounds):
        if selected is not None:break
        if pending:
            actions, pending = pending, []
        else:
            for attempt in range(3):
                try:
                    decision, metadata = controller.next(history)
                    break
                except (ControllerUnavailable, subprocess.TimeoutExpired) as error:
                    log({'controller_interruption':{'round_number':round_number,'attempt':attempt + 1,
                                                   'kind':type(error).__name__}})
                    if attempt == 2:raise
                    time.sleep(2 * (attempt + 1))
            log({"round": round_number, "controller": metadata, "decision": decision})
            actions = decision.get("actions")
        if not isinstance(actions, list) or not 1 <= len(actions) <= 4:
            raise ValueError("controller action budget exceeded")
        for action in actions:
            try:
                tool, kw = action["tool"], json.loads(action["arguments"])
                if tool == "inspect":
                    tensor = original[kw["tensor"]]
                    start, count = kw["start"], kw["count"]
                    if type(start) is not int or type(count) is not int or start < 0 or not 1 <= count <= 256 or start + count > tensor.numel():
                        raise ValueError("invalid inspection range")
                    flat = tensor.flatten().float()
                    result = {**inventory[kw["tensor"]], "values": flat[start:start + count].tolist(),
                              "mean": float(flat.mean()), "std": float(flat.std(unbiased=False)), "norm": float(flat.norm())}
                    inspected.add(kw["tensor"])
                elif tool == "tokenize":
                    if not isinstance(kw["text"], str) or len(kw["text"]) > 4096:
                        raise ValueError("text budget exceeded")
                    result = {"ids": tokenizer.encode(kw["text"], add_special_tokens=False)}
                elif tool == "inspect_diff":
                    from weight_handoff import inspect_diff
                    if parent_diff is None:
                        raise ValueError("no inherited experiment")
                    result = inspect_diff(parent_diff, kw["tensor"], kw["start"], kw["count"])
                    diff_inspected = diff_inspected or bool(result["changes"])
                elif tool == "contrast":
                    positive, negative = kw["positive_label"], kw["negative_label"]
                    if type(positive) is not int or type(negative) is not int:
                        raise ValueError("contrast labels must be integers")
                    name = f"activation_contrast.{positive}.{negative}"
                    if name in features:
                        raise ValueError("this contrast was already computed")
                    model.load_state_dict(original, strict=False)
                    vector, projections = activation_contrast(model, tokenizer, development, config, positive, negative)
                    features[name] = vector
                    result = {"source_tensor": name, "shape": list(vector.shape), "norm": float(vector.norm()),
                              "class_projections": projections, "formula": "unit(mean(base_hidden_positive)-mean(base_hidden_negative))",
                              "values": vector.tolist()}
                elif tool == "experiment":
                    if probes >= args.max_probes:
                        raise ValueError("probe budget exhausted; select a candidate")
                    probes += 1
                    if handoff and not diff_inspected:
                        raise ValueError("inspect actual parent diff values before editing its checkpoint")
                    if not kw["hypothesis"] or len(kw["hypothesis"]) > 8000:
                        raise ValueError("hypothesis required")
                    if not all(op["tensor"] in inspected for op in kw["operations"]):
                        raise ValueError("inspect each destination tensor before editing")
                    validate_edit_scope(config, kw['operations'])
                    edits = edited_slices({**original, **features}, kw["operations"], edit_limit)
                    model.load_state_dict(original, strict=False)
                    state = model.state_dict()
                    for op, values in edits:
                        state[op["tensor"]].flatten()[op["start"]:op["start"] + op["count"]].copy_(values)
                    result = {"candidate": len(candidates), **score(model, tokenizer, development, development_config)}
                    candidates.append({"id": len(candidates), "hypothesis": kw["hypothesis"],
                                       "operations": kw["operations"], "development": result})
                    print(f"candidate {result['candidate']}: dev accuracy={result['accuracy']:.4f} label_nll={result['label_nll']:.6f}", flush=True)
                elif tool == "finish":
                    if probes < args.min_probes:
                        raise ValueError(f"exploration budget requires at least {args.min_probes} attempts before finalization")
                    selected = kw["candidate"]
                    if type(selected) is not int or not 0 <= selected < len(candidates):
                        raise ValueError("select a tested candidate")
                    result = {"frozen_candidate": selected, "reason": kw["reason"]}
                else:
                    raise ValueError("unknown tool")
            except (ValueError, KeyError, TypeError, IndexError) as error:
                result = {"error": str(error)}
                selected = None
            entry = {"action": action, "result": result}
            history.append(entry)
            log(entry)
            if selected is not None:
                break
        if selected is not None:
            break
    if selected is None:
        raise RuntimeError("controller did not finalize a candidate within its budget")
    winner = candidates[selected]
    edits = edited_slices({**original, **features}, winner["operations"], edit_limit)
    changed = save_candidate(args.model / "model.safetensors", args.output / "candidate.safetensors", edits)
    result = {"schema": "nc/weight-agent-session/v1", "commitment": commitment,
              "baseline_development": baseline, "selected": winner, "candidates": candidates,
              "probes": probes, "changed_parameters": changed,
              "total_parameters": sum(t.numel() for t in original.values()),
              "candidate_sha256": sha(args.output / "candidate.safetensors"),
              "transcript_sha256": sha(args.output / "transcript.jsonl"), "gradients_used": False,
              "feature_vectors": {name: vector.tolist() for name, vector in features.items()}}
    write(args.output / "session.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["model", "config", "development", "source", "output"]:
        parser.add_argument("--" + name, type=pathlib.Path, required=True)
    parser.add_argument("--backend", choices=["codex", "openai"], required=True)
    parser.add_argument("--controller-model", required=True)
    parser.add_argument("--heldout-sha256", required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--selection-sha256")
    parser.add_argument("--handoff", type=pathlib.Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=16)
    parser.add_argument("--max-probes", type=int, default=8)
    parser.add_argument("--min-probes", type=int, default=0)
    parser.add_argument("--max-edit-elements", type=int, default=2000000)
    parser.add_argument("--controller-timeout", type=int, default=180)
    options = parser.parse_args()
    if not 0 <= options.min_probes <= options.max_probes:
        parser.error("require 0 <= min-probes <= max-probes")
    if not all(len(h) == 64 and all(c in "0123456789abcdef" for c in h)
               for h in [options.heldout_sha256, options.policy_sha256]):
        parser.error("held-out and policy commitments must be SHA256 hex digests")
    run(options)
