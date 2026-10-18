"""Pure budget regression checks; no Telegram sessions or model loads."""
import ast
import os
from pathlib import Path
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ConversionTimeoutTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / "bobby/helpers/_voiceconv.py").read_text())
        nodes = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_cpu_scale", "_job_timeout"}
        ]
        self.ns = dict(os=os, THREADS=4, STEPS=25, REF_SECONDS=25, MAX_SECONDS=60)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "<budget>", "exec"), self.ns)

    def budget(self, cpus, seconds=1.2, **kwargs):
        with patch.object(os, "sched_getaffinity", return_value=set(range(cpus))), \
             patch.object(os.path, "getsize", return_value=seconds * 176400):
            return self.ns["_job_timeout"]("unused.wav", **kwargs)

    def test_two_cpu_short_conversion_keeps_reference_budget(self):
        budget = self.budget(2, steps=20, ref_seconds=12)
        self.assertAlmostEqual(budget, 324.0)
        self.assertEqual(budget, 2 * self.budget(4, steps=20, ref_seconds=12))

    def test_reference_and_steps_affect_work(self):
        self.assertGreater(self.budget(4, ref_seconds=25), self.budget(4, ref_seconds=12))
        self.assertGreater(self.budget(4, steps=25), self.budget(4, steps=20))
        self.assertGreaterEqual(self.budget(4), 90 + 12 * 1.2)

    def test_unknown_input_has_bounded_conservative_budget(self):
        with patch.object(os, "sched_getaffinity", return_value={0}), \
             patch.object(os.path, "getsize", side_effect=OSError):
            self.assertEqual(self.ns["_job_timeout"]("missing.wav"), 1800)
        self.assertEqual(self.budget(1, seconds=10000), 1800)

    def test_cpu_fallback_and_thread_limit(self):
        with patch.object(os, "sched_getaffinity", side_effect=OSError), \
             patch.object(os, "cpu_count", return_value=2):
            self.assertEqual(self.ns["_cpu_scale"](), 2)
        self.ns["THREADS"] = 2
        with patch.object(os, "sched_getaffinity", return_value=set(range(8))):
            self.assertEqual(self.ns["_cpu_scale"](), 2)

    def test_short_status_estimates_follow_cpu_budget(self):
        tree = ast.parse((ROOT / "bobby/helpers/_shortclone.py").read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "estimate_seconds")
        vc = types.SimpleNamespace(warm=lambda: False, _cpu_scale=lambda: 2)
        ns = {"voiceconv": vc}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<estimate>", "exec"), ns)
        self.assertEqual(ns["estimate_seconds"](), 200)
        vc.warm = lambda: True
        self.assertEqual(ns["estimate_seconds"](), 120)


if __name__ == "__main__":
    unittest.main()