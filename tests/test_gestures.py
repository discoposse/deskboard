#!/usr/bin/env python3
"""Run the canvas gesture math checks."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GestureMathTests(unittest.TestCase):
    def test_insertion_and_span_math(self):
        script = ROOT / "tests" / "gestures_check.mjs"
        proc = subprocess.run(
            ["node", "--test", str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
