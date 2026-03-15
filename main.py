from __future__ import annotations

import argparse
import json
import os
from typing import Any

from deepagents import create_deep_agent

from deepagent_lang import build_e2b_code_execution_tool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Deep Agent with E2B-backed Python tools."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Task to send to the deep agent.",
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=[],
        help="Local workspace file the agent may pass into the E2B tool.",
    )
    parser.add_argument(
        "--agent-model",
        default=os.environ.get("DEEPAGENT_MODEL", "openai:gpt-4o-mini"),
        help="Model passed to create_deep_agent(...).",
    )
    return parser.parse_args()


def build_tools() -> tuple[list[Any], str]:
    tools = [build_e2b_code_execution_tool()]
    system_prompt = (
        "Use `execute_python_in_e2b` whenever a task would benefit from writing or running Python. "
        "Write the code yourself and pass only user-supplied workspace file paths to the tool."
    )
    return tools, system_prompt


def build_user_prompt(prompt: str, files: list[str]) -> str:
    if not files:
        return prompt

    file_list = "\n".join(f"- {file_path}" for file_path in files)
    return (
        f"{prompt}\n\n"
        "Workspace files available for tool calls:\n"
        f"{file_list}"
    )


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content)


def main() -> None:
    args = parse_args()
    if not args.prompt:
        print("Example:")
        print(
            '  python main.py "Analyze sample_data/expenses.csv and summarize the top 5 expense categories." '
            "--file sample_data/expenses.csv"
        )
        return

    tools, system_prompt = build_tools()
    agent = create_deep_agent(
        model=args.agent_model,
        tools=tools,
        system_prompt=system_prompt,
    )
    response = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": build_user_prompt(args.prompt, args.files),
                }
            ]
        }
    )

    messages = response.get("messages", [])
    if not messages:
        print(json.dumps(response, indent=2, default=str))
        return

    print(extract_text(messages[-1].content))


if __name__ == "__main__":
    main()
