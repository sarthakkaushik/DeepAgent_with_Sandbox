"""Utilities for wiring Python execution backends into LangChain Deep Agents."""

from deepagent_lang.local_python_tool import (
    LocalPythonRunner,
    build_local_python_execution_tool,
)

try:
    from deepagent_lang.e2b_analysis_tool import (
        E2BCodeRunner,
        build_e2b_code_execution_tool,
    )
except ModuleNotFoundError:  # pragma: no cover - optional dependency at import time
    E2BCodeRunner = None
    build_e2b_code_execution_tool = None

__all__ = [
    "E2BCodeRunner",
    "LocalPythonRunner",
    "build_e2b_code_execution_tool",
    "build_local_python_execution_tool",
]
