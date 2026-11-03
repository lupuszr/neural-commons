"""Invariant tests for untrusted controller edits and the exact file artifact."""
import json
import pathlib
import struct
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load_file, save_file
from weight_agent import Controller, edited_slices, save_candidate


def operation(**extra):
    return dict({"tensor": "w", "start": 1, "count": 2, "scale": 2,
                 "add_tensor": None, "add_start": 0, "add_scale": 0}, **extra)


class Edits(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
