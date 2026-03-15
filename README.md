# Deep Agent + E2B Tooling

This repo now includes a small E2B-backed Python execution tool for LangChain Deep Agents.

## What it does

- `deepagent_lang/e2b_analysis_tool.py`
  - `build_e2b_code_execution_tool()`: thin wrapper around E2B execution.
  - `E2BCodeRunner`: optional reusable runner if you want to hold onto the sandbox/context yourself.
- `main.py`
  - Minimal demo CLI that wires the tool into `create_deep_agent(...)`.

## Why this version is intentionally small

The deep agent already has the model and planning loop. This wrapper only adds the pieces that are usually worth keeping:

- structured JSON result with `main_result`, `stdout`, `stderr`, and `error`
- optional workspace file upload
- optional sandbox/context reuse across calls

## Environment

Set:

- `OPENAI_API_KEY`
- `E2B_API_KEY`

Optional:

- `DEEPAGENT_MODEL`

## Example

```python
from deepagents import create_deep_agent

from deepagent_lang import build_e2b_code_execution_tool

python_tool = build_e2b_code_execution_tool()

agent = create_deep_agent(
    model="openai:gpt-4o-mini",
    tools=[python_tool],
    system_prompt=(
        "Use execute_python_in_e2b whenever Python execution will help. "
        "Write the code yourself and pass it directly to the tool."
    ),
)

result = agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "Analyze sample_data/expenses.csv and tell me the top 5 "
                    "categories by total spend."
                ),
            }
        ]
    }
)

print(result["messages"][-1].content)
```

## Demo CLI

```bash
python main.py "Analyze sample_data/expenses.csv and summarize the top 5 categories." --file sample_data/expenses.csv
```
