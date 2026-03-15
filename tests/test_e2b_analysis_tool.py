from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from e2b.exceptions import TimeoutException
from e2b_code_interpreter.models import Context, Execution, ExecutionError, Logs, Result

from deepagent_lang.e2b_analysis_tool import E2BCodeRunner, strip_code_fences


class FakeFiles:
    def __init__(self, make_dir_error: Exception | None = None) -> None:
        self.created_dirs: list[str] = []
        self.writes: list[tuple[str, bytes]] = []
        self.make_dir_error = make_dir_error

    def make_dir(self, path: str) -> bool:
        if self.make_dir_error is not None:
            raise self.make_dir_error
        self.created_dirs.append(path)
        return True

    def write(self, path: str, data: bytes) -> SimpleNamespace:
        self.writes.append((path, data))
        return SimpleNamespace(path=path)


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def run(self, cmd: str, timeout: int | None = None) -> SimpleNamespace:
        self.calls.append((cmd, timeout))
        return SimpleNamespace(exit_code=0, stdout="installed", stderr="")


class FakeSandbox:
    def __init__(
        self,
        executions: list[Execution],
        sandbox_id: str = "sbx-1",
        *,
        make_dir_error: Exception | None = None,
        kill_error: Exception | None = None,
    ) -> None:
        self.executions = executions
        self.sandbox_id = sandbox_id
        self.files = FakeFiles(make_dir_error=make_dir_error)
        self.commands = FakeCommands()
        self.killed = False
        self.kill_error = kill_error
        self.run_code_calls: list[dict[str, object]] = []
        self.created_contexts = 0

    def create_code_context(self) -> Context:
        self.created_contexts += 1
        return Context(
            context_id=f"ctx-{self.created_contexts}",
            language="python",
            cwd="/home/user",
        )

    def run_code(
        self,
        code: str,
        context: Context | None = None,
        timeout: int | None = None,
        **_: object,
    ) -> Execution:
        self.run_code_calls.append(
            {
                "code": code,
                "context": context,
                "timeout": timeout,
            }
        )
        return self.executions.pop(0)

    def kill(self) -> bool:
        self.killed = True
        if self.kill_error is not None:
            raise self.kill_error
        return True


class FakeSandboxFactory:
    def __init__(self, sandboxes: list[FakeSandbox]) -> None:
        self.sandboxes = sandboxes
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> FakeSandbox:
        self.calls.append(kwargs)
        return self.sandboxes.pop(0)


class E2BCodeRunnerTests(unittest.TestCase):
    def test_strip_code_fences(self) -> None:
        self.assertEqual(
            strip_code_fences("```python\nprint('hello')\n```"),
            "print('hello')",
        )

    def test_execute_uploads_files_and_reuses_context(self) -> None:
        sandbox = FakeSandbox(
            executions=[
                Execution(
                    results=[Result(text="4", is_main_result=True)],
                    logs=Logs(stdout=["ran"], stderr=[]),
                ),
                Execution(
                    results=[Result(text="9", is_main_result=True)],
                    logs=Logs(stdout=["ran again"], stderr=[]),
                ),
            ]
        )
        factory = FakeSandboxFactory([sandbox])
        runner = E2BCodeRunner(
            sandbox_factory=factory,
            reuse_context=True,
        )
        runner.workspace_root = Path.cwd().resolve()

        first = json.loads(
            runner.execute(
                code="```python\nfinal_answer = 4\nfinal_answer\n```",
                files=["tests/fixtures/numbers.csv"],
                python_packages=["pandas"],
            )
        )
        second = json.loads(
            runner.execute(
                code="final_answer = 9\nfinal_answer",
                reset_sandbox=False,
            )
        )

        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(sandbox.created_contexts, 1)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["main_result"], "4")
        self.assertEqual(second["context_id"], "ctx-1")
        self.assertEqual(sandbox.run_code_calls[0]["context"].id, "ctx-1")
        self.assertEqual(sandbox.run_code_calls[1]["context"].id, "ctx-1")
        self.assertEqual(sandbox.files.writes[0][0], "/home/user/input/01_numbers.csv")
        self.assertIn("python -m pip install pandas", sandbox.commands.calls[0][0])

    def test_execute_returns_structured_error(self) -> None:
        sandbox = FakeSandbox(
            executions=[
                Execution(
                    error=ExecutionError(
                        name="NameError",
                        value="name 'x' is not defined",
                        traceback="Traceback: x is missing",
                    ),
                    logs=Logs(stdout=["before failure"], stderr=["boom"]),
                )
            ]
        )
        factory = FakeSandboxFactory([sandbox])
        runner = E2BCodeRunner(
            sandbox_factory=factory,
            reuse_context=False,
        )

        result = json.loads(runner.execute(code="print('before failure')\nx"))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["stdout"], ["before failure"])
        self.assertEqual(result["stderr"], ["boom"])
        self.assertEqual(result["error"]["name"], "NameError")
        self.assertTrue(sandbox.killed)

    def test_execute_retries_once_when_cached_sandbox_has_expired(self) -> None:
        stale_sandbox = FakeSandbox(
            executions=[],
            sandbox_id="stale-sbx",
            make_dir_error=TimeoutException("The sandbox was not found"),
            kill_error=TimeoutException("The sandbox was not found"),
        )
        fresh_sandbox = FakeSandbox(
            executions=[
                Execution(
                    results=[Result(text="42", is_main_result=True)],
                    logs=Logs(stdout=["recovered"], stderr=[]),
                )
            ],
            sandbox_id="fresh-sbx",
        )
        factory = FakeSandboxFactory([fresh_sandbox])
        runner = E2BCodeRunner(
            sandbox_factory=factory,
            reuse_context=True,
        )
        runner.workspace_root = Path.cwd().resolve()
        runner._sandbox = stale_sandbox
        runner._context = Context(
            context_id="stale-ctx",
            language="python",
            cwd="/home/user",
        )

        result = json.loads(
            runner.execute(
                code="final_answer = 42\nfinal_answer",
                files=["tests/fixtures/numbers.csv"],
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["main_result"], "42")
        self.assertEqual(result["sandbox_id"], "fresh-sbx")
        self.assertEqual(len(factory.calls), 1)
        self.assertTrue(stale_sandbox.killed)
        self.assertEqual(fresh_sandbox.created_contexts, 1)


if __name__ == "__main__":
    unittest.main()
