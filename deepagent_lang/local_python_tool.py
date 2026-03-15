from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field


LOCAL_INPUT_DIR = "input"
LOCAL_RUNNER_SCRIPT = "_deepagent_local_runner.py"
LOCAL_USER_CODE = "user_code.py"
LOCAL_RESULT_FILE = "result.json"
LOCAL_STDOUT_FILE = "stdout.log"
LOCAL_STDERR_FILE = "stderr.log"

LOCAL_RUNNER_SOURCE = dedent(
    """
    import ast
    import json
    import traceback
    from contextlib import redirect_stderr, redirect_stdout
    from pathlib import Path

    USER_CODE_PATH = Path("user_code.py")
    RESULT_PATH = Path("result.json")
    STDOUT_PATH = Path("stdout.log")
    STDERR_PATH = Path("stderr.log")


    def _instrument_code(source: str):
        tree = ast.parse(source, filename=str(USER_CODE_PATH))
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = tree.body[-1]
            assign = ast.Assign(
                targets=[ast.Name(id="_deepagent_main_result", ctx=ast.Store())],
                value=last_expr.value,
            )
            tree.body[-1] = ast.copy_location(assign, last_expr)
            ast.fix_missing_locations(tree)
        return compile(tree, str(USER_CODE_PATH), "exec")


    def _json_safe(value):
        try:
            json.dumps(value)
            return value
        except TypeError:
            return repr(value)


    def main():
        payload = {
            "status": "ok",
            "main_result": None,
            "error": None,
        }

        source = USER_CODE_PATH.read_text(encoding="utf-8")
        namespace = {
            "__name__": "__main__",
            "__file__": str(USER_CODE_PATH),
        }

        with STDOUT_PATH.open("w", encoding="utf-8", buffering=1) as stdout_handle:
            with STDERR_PATH.open("w", encoding="utf-8", buffering=1) as stderr_handle:
                try:
                    compiled = _instrument_code(source)
                    with redirect_stdout(stdout_handle), redirect_stderr(stderr_handle):
                        exec(compiled, namespace)

                    main_result = namespace.get(
                        "_deepagent_main_result",
                        namespace.get("final_answer"),
                    )
                    payload["main_result"] = _json_safe(main_result)
                except Exception as exc:
                    traceback_text = traceback.format_exc()
                    stderr_handle.write(traceback_text)
                    stderr_handle.flush()
                    payload["status"] = "error"
                    payload["error"] = {
                        "name": type(exc).__name__,
                        "value": str(exc),
                        "traceback": traceback_text,
                    }

        RESULT_PATH.write_text(json.dumps(payload), encoding="utf-8")


    if __name__ == "__main__":
        main()
    """
).strip()


@dataclass(frozen=True)
class LocalUploadedFile:
    local_path: str
    runtime_path: str


class LocalPythonExecutionInput(BaseModel):
    code: str = Field(
        ...,
        description="Executable Python code to run on the local machine in a fresh temp directory.",
    )
    files: list[str] = Field(
        default_factory=list,
        description="Workspace file paths to copy into the temp execution directory before running.",
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="Optional per-call timeout. Uses the runner default when omitted.",
    )


class LocalPythonRunner:
    """Run trusted Python one-shot on the host machine in a fresh temp directory."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        python_executable: str | None = None,
        execution_timeout_seconds: int = 30,
        max_output_chars: int = 6_000,
        max_log_lines: int = 40,
    ) -> None:
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self.python_executable = python_executable or sys.executable
        self.execution_timeout_seconds = execution_timeout_seconds
        self.max_output_chars = max_output_chars
        self.max_log_lines = max_log_lines

    def build_tool(self, tool_name: str = "execute_python_locally") -> BaseTool:
        def _tool(
            code: str,
            files: list[str] | None = None,
            timeout_seconds: int | None = None,
        ) -> str:
            """Execute trusted Python locally and return structured JSON with logs and errors."""

            return self.execute(
                code=code,
                files=files or [],
                timeout_seconds=timeout_seconds,
            )

        return tool(tool_name, args_schema=LocalPythonExecutionInput)(_tool)

    def execute(
        self,
        *,
        code: str,
        files: Sequence[str] = (),
        timeout_seconds: int | None = None,
    ) -> str:
        cleaned_code = strip_code_fences(code)
        runtime_root = self._create_runtime_root()
        try:
            uploaded_files = self._stage_files(runtime_root, files)
            (runtime_root / LOCAL_USER_CODE).write_text(cleaned_code, encoding="utf-8")
            (runtime_root / LOCAL_RUNNER_SCRIPT).write_text(
                LOCAL_RUNNER_SOURCE,
                encoding="utf-8",
            )

            try:
                completed = subprocess.run(
                    [self.python_executable, LOCAL_RUNNER_SCRIPT],
                    cwd=runtime_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds or self.execution_timeout_seconds,
                    env=self._build_env(),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return json.dumps(
                    {
                        "status": "error",
                        "backend": "local_python",
                        "python_executable": self.python_executable,
                        "uploaded_files": [asdict(item) for item in uploaded_files],
                        "executed_code": self._clip_text(cleaned_code),
                        "main_result": None,
                        "stdout": self._read_log_lines(runtime_root / LOCAL_STDOUT_FILE),
                        "stderr": self._read_log_lines(runtime_root / LOCAL_STDERR_FILE),
                        "exit_code": None,
                        "error": {
                            "name": "TimeoutExpired",
                            "value": f"Execution exceeded {timeout_seconds or self.execution_timeout_seconds} seconds.",
                            "traceback": self._clip_text(str(exc)),
                        },
                    },
                    indent=2,
                )

            return self._format_summary(
                runtime_root=runtime_root,
                uploaded_files=uploaded_files,
                code=cleaned_code,
                completed=completed,
            )
        finally:
            shutil.rmtree(runtime_root, ignore_errors=True)

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        if existing_pythonpath:
            env["PYTHONPATH"] = (
                f"{self.workspace_root}{os.pathsep}{existing_pythonpath}"
            )
        else:
            env["PYTHONPATH"] = str(self.workspace_root)
        return env

    def _create_runtime_root(self) -> Path:
        runtime_root = self.workspace_root / f".deepagent-local-python-{uuid.uuid4().hex[:8]}"
        runtime_root.mkdir(parents=True, exist_ok=False)
        return runtime_root

    def _stage_files(
        self,
        runtime_root: Path,
        files: Sequence[str],
    ) -> list[LocalUploadedFile]:
        uploaded_files: list[LocalUploadedFile] = []
        if not files:
            return uploaded_files

        for file_path in files:
            local_path = self._resolve_workspace_file(file_path)
            relative_path = local_path.relative_to(self.workspace_root)
            runtime_path = Path(LOCAL_INPUT_DIR) / relative_path
            destination = runtime_root / runtime_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, destination)
            uploaded_files.append(
                LocalUploadedFile(
                    local_path=str(local_path),
                    runtime_path=runtime_path.as_posix(),
                )
            )

        return uploaded_files

    def _resolve_workspace_file(self, file_path: str) -> Path:
        candidate = Path(file_path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate

        resolved = candidate.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {resolved}")
        if not resolved.is_file():
            raise ValueError(f"Expected a file path, got: {resolved}")
        if self.workspace_root not in resolved.parents and resolved != self.workspace_root:
            raise ValueError(
                f"File must be inside the workspace root: {self.workspace_root}"
            )
        return resolved

    def _format_summary(
        self,
        *,
        runtime_root: Path,
        uploaded_files: Sequence[LocalUploadedFile],
        code: str,
        completed: subprocess.CompletedProcess[str],
    ) -> str:
        result_payload = self._read_result_payload(runtime_root)
        wrapper_stdout = completed.stdout.strip()
        wrapper_stderr = completed.stderr.strip()

        error = result_payload.get("error")
        if completed.returncode != 0 and error is None:
            error = {
                "name": "RunnerProcessError",
                "value": "The local runner process exited before producing a structured result.",
                "traceback": self._clip_text(
                    "\n".join(part for part in [wrapper_stdout, wrapper_stderr] if part)
                ),
            }

        summary = {
            "status": "error" if error else result_payload.get("status", "ok"),
            "backend": "local_python",
            "python_executable": self.python_executable,
            "uploaded_files": [asdict(item) for item in uploaded_files],
            "executed_code": self._clip_text(code),
            "main_result": result_payload.get("main_result"),
            "stdout": self._read_log_lines(runtime_root / LOCAL_STDOUT_FILE),
            "stderr": self._read_log_lines(runtime_root / LOCAL_STDERR_FILE),
            "exit_code": completed.returncode,
            "error": error,
        }
        return json.dumps(summary, indent=2)

    def _read_result_payload(self, runtime_root: Path) -> dict[str, Any]:
        result_path = runtime_root / LOCAL_RESULT_FILE
        if not result_path.exists():
            return {
                "status": "error",
                "main_result": None,
                "error": {
                    "name": "MissingResultFile",
                    "value": "The local runner did not write a result file.",
                    "traceback": None,
                },
            }

        return json.loads(result_path.read_text(encoding="utf-8"))

    def _read_log_lines(self, path: Path) -> list[str]:
        if not path.exists():
            return []

        text = path.read_text(encoding="utf-8")
        if not text:
            return []
        return text.splitlines()[-self.max_log_lines :]

    def _clip_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) <= self.max_output_chars:
            return value
        return f"{value[: self.max_output_chars]}... [truncated]"


def build_local_python_execution_tool(
    *,
    workspace_root: str | Path | None = None,
    python_executable: str | None = None,
    execution_timeout_seconds: int = 30,
) -> BaseTool:
    runner = LocalPythonRunner(
        workspace_root=workspace_root,
        python_executable=python_executable,
        execution_timeout_seconds=execution_timeout_seconds,
    )
    return runner.build_tool()


def strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
