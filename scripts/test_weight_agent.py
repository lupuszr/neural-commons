"""Invariant tests for untrusted controller edits and the exact file artifact."""
import json
import pathlib
import struct
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load_file, save_file
from weight_agent import Controller, edited_slices, save_candidate, validate_edit_scope
from select_weight_candidate import choose
from summarize_weight_result import summarize
from llm_runtime import activation_contrast, guard_passes


def operation(**extra):
    return dict({"tensor": "w", "start": 1, "count": 2, "scale": 2,
                 "add_tensor": None, "add_start": 0, "add_scale": 0}, **extra)


class Edits(unittest.TestCase):
    def test_user_selected_scope_is_enforced_but_whole_model_allows_other_weights(self):
        from continuation_job import apply_user_controls
        manifest={'tensors':[{'name':'w','shape':[4]},{'name':'other','shape':[2]}]}
        config=apply_user_controls({}, {'weight_scope':{'mode':'selected','tensors':['w']}}, manifest)
        validate_edit_scope(config,[operation()])
        with self.assertRaisesRegex(ValueError,'operator-approved'):
            validate_edit_scope(config,[operation(tensor='other',start=0,count=1)])
        with self.assertRaisesRegex(ValueError,'operator-approved'):
            validate_edit_scope(config,[operation(start=3,count=2)])
        unrestricted=apply_user_controls(config,{'weight_scope':{'mode':'all'}},manifest)
        validate_edit_scope(unrestricted,[operation(tensor='other',start=0,count=1)])

    def setUp(self):
        self.original = {"w": torch.tensor([1., 2., 3., 4.], dtype=torch.bfloat16),
                         "other": torch.tensor([9., 8.], dtype=torch.bfloat16)}

    def test_file_preserves_header_untouched_bytes_and_dtype(self):
        with tempfile.TemporaryDirectory() as d:
            base, candidate = pathlib.Path(d) / "base", pathlib.Path(d) / "candidate"
            save_file(self.original, base, metadata={"source": "test"})
            raw = base.read_bytes()
            edits = edited_slices(self.original, [operation()], 2)
            self.assertEqual(save_candidate(base, candidate, edits), 2)
            result = load_file(candidate)
            self.assertEqual(result["w"].tolist(), [1, 4, 6, 4])
            self.assertTrue(torch.equal(result["other"], self.original["other"]))
            header_size = 8 + struct.unpack("<Q", raw[:8])[0]
            self.assertEqual(raw[:header_size], candidate.read_bytes()[:header_size])
            self.assertEqual(result["w"].dtype, torch.bfloat16)
            self.assertFalse(edits[0][1].requires_grad)
            self.assertEqual(self.original["w"].tolist(), [1, 2, 3, 4])

    def test_rejects_budget_overlap_nonfinite_and_noop(self):
        cases = [[operation(count=4)], [operation(), operation(start=2)],
                 [operation(scale=float("nan"))], [operation(scale=1)],
                 [operation(add_tensor="missing", add_scale=1)], [operation(start=-1)]]
        for operations in cases:
            with self.subTest(operations=operations), self.assertRaises(ValueError):
                edited_slices(self.original, operations, 3)

    def test_sources_are_pristine_and_bfloat16_rounding_precedes_inference(self):
        operations = [operation(start=0, count=2), operation(start=2, count=2, scale=0,
                      add_tensor="w", add_start=0, add_scale=1)]
        edits = edited_slices(self.original, operations, 4)
        self.assertEqual(edits[0][1].tolist(), [2, 4])
        self.assertEqual(edits[1][1].tolist(), [1, 2])

    @patch("weight_agent.subprocess.run")
    def test_codex_uses_login_and_disables_native_tools(self, run):
        def respond(command, **kw):
            self.assertNotIn("OPENAI_API_KEY", kw["env"])
            self.assertIn("--ignore-user-config", command)
            self.assertIn("features.shell_tool=false", command)
            self.assertIn("features.apps=false", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            output = pathlib.Path(command[command.index("--output-last-message") + 1])
            output.write_text(json.dumps({"actions": [{"tool": "tokenize", "arguments": '{"text":"good"}'}]}))
            return type("Result", (), {"returncode": 0, "stdout": '{"type":"turn.completed","usage":{}}'})()
        run.side_effect = respond
        result, metadata = Controller("codex", "operator-model").next([{"development": "visible"}])
        self.assertEqual(result["actions"][0]["tool"], "tokenize")
        self.assertEqual(metadata["native_tool_calls"], 0)

    @patch.dict("weight_agent.os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("weight_agent.urllib.request.urlopen")
    def test_api_uses_same_action_contract_without_native_tools(self, urlopen):
        import io
        decision = {"actions": [{"tool": "inspect", "arguments": '{"tensor":"w","start":0,"count":2}'}]}
        response = {"status": "completed", "model": "operator-model", "id": "test-response",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(decision)}]}]}
        urlopen.return_value = io.BytesIO(json.dumps(response).encode())
        actual, metadata = Controller("openai", "operator-model").next([{"development": "visible"}])
        request = urlopen.call_args[0][0]
        body = json.loads(request.data)
        self.assertFalse(body["store"])
        self.assertNotIn("tools", body)
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(actual, decision)
        self.assertEqual(metadata["response_id"], "test-response")

    def test_selection_rejects_confidence_only_and_nll_regressions(self):
        base = {"accuracy": 0.75, "label_nll": 0.5}
        policy = {"min_accuracy_improvement": 0.01, "max_nll_regression": 0.0}
        candidates = [
            {"id": 0, "selection": {"accuracy": 0.75, "label_nll": 0.1}},
            {"id": 1, "selection": {"accuracy": 0.9, "label_nll": 0.6}},
            {"id": 2, "selection": {"accuracy": 0.8, "label_nll": 0.4}},
            {"id": 3, "selection": {"accuracy": 0.8, "label_nll": 0.3}},
            {"id": 4, "selection": {"accuracy": 0.8, "label_nll": 0.3}},
        ]
        self.assertEqual(choose(candidates, base, policy)["id"], 3)
        self.assertIsNone(choose(candidates[:2], base, policy))
        candidates[3]["guard_passed"] = candidates[4]["guard_passed"] = False
        self.assertEqual(choose(candidates, base, policy)["id"], 2)

    def test_paired_statistics_detect_regressions_and_alignment_errors(self):
        before = [{"id": i, "label": 0, "prediction": int(i < 4)} for i in range(8)]
        after = [{"id": i, "label": 0, "prediction": 0} for i in range(8)]
        output = {"details": {
            "base": {"predictions": before, "samples": 8, "accuracy": 0.5, "label_nll": 0.6},
            "candidate": {"predictions": after, "samples": 8, "accuracy": 1., "label_nll": 0.2}}}
        stats = summarize(output)
        self.assertEqual((stats["corrected"], stats["regressed"]), (4, 0))
        self.assertEqual(stats["mcnemar_exact_two_sided_p"], 0.125)
        after[0]["id"] = 100
        with self.assertRaises(ValueError):
            summarize(output)

    def test_activation_contrast_uses_class_means_without_gradients(self):
        from types import SimpleNamespace
        class Batch(dict):
            def to(self, device):
                return self
        class Tokenizer:
            def __call__(self, prompts, **kwargs):
                return Batch(input_ids=torch.tensor([[int(x)] for x in prompts]))
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.zeros(1))
            def forward(self, input_ids, output_hidden_states):
                assert not torch.is_grad_enabled()
                states = torch.tensor([[1., 0.], [3., 0.], [0., 1.], [0., 3.]])[input_ids]
                return SimpleNamespace(hidden_states=[states])
        dataset = {"samples": [{"text": str(i), "label": int(i >= 2)} for i in range(4)]}
        config = {"labels": ["positive", "negative"], "prompt": "{text}", "batch_size": 2, "max_tokens": 8}
        vector, stats = activation_contrast(Model(), Tokenizer(), dataset, config, 0, 1)
        self.assertTrue(torch.allclose(vector, torch.tensor([2**-0.5, -2**-0.5])))
        self.assertEqual(stats["0"]["samples"], 2)
        self.assertFalse(vector.requires_grad)
        rest, _ = activation_contrast(Model(), Tokenizer(), dataset, config, 0, -1)
        self.assertTrue(torch.equal(vector, rest))

    def test_sentiment_guard_blocks_accuracy_or_nll_regression(self):
        base = {"accuracy": 0.98, "label_nll": 0.3}
        policy = {"max_accuracy_drop": 0.0, "max_nll_increase": 1e-6}
        self.assertTrue(guard_passes(base, base, policy))
        self.assertFalse(guard_passes(base, {"accuracy": 0.97, "label_nll": 0.2}, policy))
        self.assertFalse(guard_passes(base, {"accuracy": 0.99, "label_nll": 0.4}, policy))

    def test_evaluator_fails_guard_even_when_main_accuracy_improves(self):
        import io
        import causal_lm
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config = {"metric": "guarded_accuracy/v1", "guard": {"dataset_artifact": "guard_data",
                      "config_artifact": "guard_config", "max_accuracy_drop": 0., "max_nll_increase": 1e-6}}
            for name, value in [("config", config), ("dataset", {"samples": [1]}),
                                ("guard-data", {}), ("guard-config", {})]:
                (root / name).write_text(json.dumps(value))
            request = {"config": str(root / "config"), "dataset": str(root / "dataset"),
                       "spec_id": "test", "spec": {"metric": "guarded_accuracy/v1", "max_samples": 1, "backend": "test"},
                       "base_files": {}, "candidate_files": {}, "inference_artifacts": {
                           "guard_data": str(root / "guard-data"), "guard_config": str(root / "guard-config")}}
            path = root / "request.json";path.write_text(json.dumps(request))
            scores = [{"accuracy": .7, "label_nll": .5}, {"accuracy": 1., "label_nll": .1},
                      {"accuracy": .9, "label_nll": .3}, {"accuracy": .8, "label_nll": .2}]
            output = io.StringIO()
            with patch("sys.argv", ["causal_lm", str(path)]), patch.object(causal_lm, "materialize"), \
                    patch.object(causal_lm, "load_model", return_value=(object(), object())), \
                    patch.object(causal_lm, "score", side_effect=scores), redirect_stdout(output):
                causal_lm.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result["candidate"], 0.0)
            self.assertEqual(result["details"]["candidate"]["accuracy"], .9)
            self.assertFalse(result["details"]["guard"]["passed"])


if __name__ == "__main__":
    unittest.main()
