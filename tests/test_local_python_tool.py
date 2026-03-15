from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from deepagent_lang.local_python_tool import LocalPythonRunner


class LocalPythonRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = LocalPythonRunner(
            workspace_root=Path.cwd(),
            python_executable=sys.executable,
            execution_timeout_seconds=1,
        )

    def test_execute_captures_stdout_and_last_expression(self) -> None:
        result = json.loads(
            self.runner.execute(
                code="""
print("starting")
2 + 2
"""
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["main_result"], 4)
        self.assertEqual(result["stdout"], ["starting"])
        self.assertEqual(result["stderr"], [])
        self.assertEqual(result["backend"], "local_python")

    def test_execute_supports_final_answer_and_uploaded_files(self) -> None:
        result = json.loads(
            self.runner.execute(
                code="""
from pathlib import Path

content = Path("input/tests/fixtures/numbers.csv").read_text(encoding="utf-8")
final_answer = content.splitlines()[0]
""",
                files=["tests/fixtures/numbers.csv"],
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["main_result"], "value")
        self.assertEqual(
            result["uploaded_files"][0]["runtime_path"],
            "input/tests/fixtures/numbers.csv",
        )

    def test_execute_returns_timeout_error(self) -> None:
        result = json.loads(
            self.runner.execute(
                code="""
import time

print("before sleep")
time.sleep(2)
""",
            )
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["name"], "TimeoutExpired")

    def test_execute_raises_for_missing_workspace_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.runner.execute(
                code="print('hello')",
                files=["tests/fixtures/does-not-exist.csv"],
            )


if __name__ == "__main__":
    unittest.main()
