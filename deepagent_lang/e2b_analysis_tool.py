from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from e2b.exceptions import NotFoundException, TimeoutException
from e2b_code_interpreter import Sandbox
from e2b_code_interpreter.models import Context, Execution
from e2b_connect.client import ConnectException
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

DEFAULT_REMOTE_INPUT_DIR = "/home/user/input"


@dataclass(frozen=True)
class UploadedFile:
    local_path: str
    remote_path: str


class CodeExecutionInput(BaseModel):
    code: str = Field(
        ...,
        description="Executable Python code to run inside the E2B sandbox.",
    )
    files: list[str] = Field(
        default_factory=list,
        description="Workspace file paths to upload into the sandbox before execution.",
    )
    python_packages: list[str] = Field(
        default_factory=list,
        description="Optional pip packages to install inside the sandbox before execution.",
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="Optional per-call execution timeout. Uses the runner default when omitted.",
    )
    reset_sandbox: bool = Field(
        default=False,
        description="Restart the cached sandbox/context before execution.",
    )


class E2BCodeRunner:
    """Small E2B wrapper for Python execution with files, logs, and optional context reuse."""

    def __init__(
        self,
        *,
        sandbox_factory: Callable[..., Any] = Sandbox.create,
        workspace_root: str | Path | None = None,
        sandbox_timeout_seconds: int = 300,
        execution_timeout_seconds: int = 120,
        package_install_timeout_seconds: int = 120,
        allow_internet_access: bool = True,
        reuse_context: bool = True,
        max_output_chars: int = 6_000,
        max_log_lines: int = 40,
    ) -> None:
        self.sandbox_factory = sandbox_factory
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self.sandbox_timeout_seconds = sandbox_timeout_seconds
        self.execution_timeout_seconds = execution_timeout_seconds
        self.package_install_timeout_seconds = package_install_timeout_seconds
        self.allow_internet_access = allow_internet_access
        self.reuse_context = reuse_context
        self.max_output_chars = max_output_chars
        self.max_log_lines = max_log_lines
        self._sandbox: Any | None = None
        self._context: Context | None = None

    def build_tool(self, tool_name: str = "execute_python_in_e2b") -> BaseTool:
        def _tool(
            code: str,
            files: list[str] | None = None,
            python_packages: list[str] | None = None,
            timeout_seconds: int | None = None,
            reset_sandbox: bool = False,
        ) -> str:
            """Execute Python in E2B and return structured JSON with result, logs, and errors."""

            return self.execute(
                code=code,
                files=files or [],
                python_packages=python_packages or [],
                timeout_seconds=timeout_seconds,
                reset_sandbox=reset_sandbox,
            )

        return tool(tool_name, args_schema=CodeExecutionInput)(_tool)

    def execute(
        self,
        *,
        code: str,
        files: Sequence[str] = (),
        python_packages: Sequence[str] = (),
        timeout_seconds: int | None = None,
        reset_sandbox: bool = False,
    ) -> str:
        cleaned_code = strip_code_fences(code)
        attempt_reset = reset_sandbox

        for attempt in range(2):
            sandbox, context, should_close = self._borrow_session(
                reset_sandbox=attempt_reset
            )

            try:
                uploaded_files = self._stage_files(sandbox, files)
                self._install_packages(sandbox, python_packages)
                execution = sandbox.run_code(
                    cleaned_code,
                    context=context,
                    timeout=timeout_seconds or self.execution_timeout_seconds,
                )
                return self._format_summary(
                    sandbox_id=sandbox.sandbox_id,
                    context_id=context.id if context else None,
                    uploaded_files=uploaded_files,
                    python_packages=python_packages,
                    code=cleaned_code,
                    execution=execution,
                )
            except Exception as exc:
                if not self._should_retry_with_fresh_sandbox(
                    exc=exc,
                    attempt=attempt,
                    should_close=should_close,
                ):
                    raise

                # When we cache sandboxes locally, the server can still expire them after
                # the configured timeout. In that case the Python object is stale even
                # though it still exists in memory. We clear the cached handles and retry
                # once with a brand-new sandbox so notebook users do not have to manually
                # rebuild the tool after every timeout.
                self.close()
                attempt_reset = False
                continue
            finally:
                if should_close:
                    sandbox.kill()

        raise RuntimeError("E2B execution retry loop exited unexpectedly.")

    def close(self) -> None:
        if self._sandbox is None:
            return
        try:
            # A stale cached sandbox may already have been deleted on the E2B side.
            # We still clear the local references so the next call can create a fresh
            # sandbox instead of trying to reuse a dead one again.
            self._sandbox.kill()
        except Exception:
            pass
        finally:
            self._sandbox = None
            self._context = None

    def _borrow_session(
        self,
        *,
        reset_sandbox: bool,
    ) -> tuple[Any, Context | None, bool]:
        if not self.reuse_context:
            sandbox = self._create_sandbox()
            return sandbox, sandbox.create_code_context(), True

        if reset_sandbox:
            self.close()

        if self._sandbox is None:
            self._sandbox = self._create_sandbox()
            self._context = self._sandbox.create_code_context()

        return self._sandbox, self._context, False

    def _create_sandbox(self) -> Any:
        return self.sandbox_factory(
            timeout=self.sandbox_timeout_seconds,
            allow_internet_access=self.allow_internet_access,
        )

    def _should_retry_with_fresh_sandbox(
        self,
        *,
        exc: Exception,
        attempt: int,
        should_close: bool,
    ) -> bool:
        if should_close or not self.reuse_context or attempt > 0:
            return False

        if isinstance(exc, (TimeoutException, NotFoundException, ConnectException)):
            message = str(exc).lower()
            return "sandbox" in message and (
                "not found" in message or "timeout" in message or "expired" in message
            )

        return False

    def _stage_files(self, sandbox: Any, files: Sequence[str]) -> list[UploadedFile]:
        uploaded_files: list[UploadedFile] = []
        if not files:
            return uploaded_files

        sandbox.files.make_dir(DEFAULT_REMOTE_INPUT_DIR)
        for index, file_path in enumerate(files, start=1):
            local_path = self._resolve_workspace_file(file_path)
            remote_path = self._remote_path_for(local_path, index)
            sandbox.files.write(remote_path, local_path.read_bytes())
            uploaded_files.append(
                UploadedFile(
                    local_path=str(local_path),
                    remote_path=remote_path,
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

    def _install_packages(self, sandbox: Any, python_packages: Sequence[str]) -> None:
        if not python_packages:
            return

        package_args = " ".join(shlex.quote(package) for package in python_packages)
        result = sandbox.commands.run(
            f"python -m pip install {package_args}",
            timeout=self.package_install_timeout_seconds,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                "Failed to install sandbox packages. "
                f"stdout={self._clip_text(result.stdout)} "
                f"stderr={self._clip_text(result.stderr)}"
            )

    def _format_summary(
        self,
        *,
        sandbox_id: str,
        context_id: str | None,
        uploaded_files: Sequence[UploadedFile],
        python_packages: Sequence[str],
        code: str,
        execution: Execution,
    ) -> str:
        summary = {
            "status": "error" if execution.error else "ok",
            "sandbox_id": sandbox_id,
            "context_id": context_id,
            "uploaded_files": [asdict(item) for item in uploaded_files],
            "installed_python_packages": list(python_packages),
            "executed_code": self._clip_text(code),
            "main_result": self._clip_text(execution.text),
            "stdout": execution.logs.stdout[-self.max_log_lines :],
            "stderr": execution.logs.stderr[-self.max_log_lines :],
            "result_formats": [list(result.formats()) for result in execution.results],
            "error": None,
        }

        if execution.error:
            summary["error"] = {
                "name": execution.error.name,
                "value": execution.error.value,
                "traceback": self._clip_text(execution.error.traceback),
            }

        return json.dumps(summary, indent=2)

    def _remote_path_for(self, local_path: Path, index: int) -> str:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", local_path.name).strip("_")
        safe_name = safe_name or f"file_{index}"
        return f"{DEFAULT_REMOTE_INPUT_DIR}/{index:02d}_{safe_name}"

    def _clip_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) <= self.max_output_chars:
            return value
        return f"{value[: self.max_output_chars]}... [truncated]"


def build_e2b_code_execution_tool(
    *,
    sandbox_timeout_seconds: int = 300,
    execution_timeout_seconds: int = 120,
    package_install_timeout_seconds: int = 120,
    allow_internet_access: bool = True,
    reuse_context: bool = True,
    workspace_root: str | Path | None = None,
) -> BaseTool:
    runner = E2BCodeRunner(
        sandbox_timeout_seconds=sandbox_timeout_seconds,
        execution_timeout_seconds=execution_timeout_seconds,
        package_install_timeout_seconds=package_install_timeout_seconds,
        allow_internet_access=allow_internet_access,
        reuse_context=reuse_context,
        workspace_root=workspace_root,
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
