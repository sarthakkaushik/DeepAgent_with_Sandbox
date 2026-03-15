# E2B Sandbox Strategy

## Goal

Use E2B as the execution backend for a Deep Agent tool so the agent can offload exact Python work instead of doing multi-step calculation in model context.

This is best treated as a deterministic execution tool, not as a second agent.

## Recommended Role of the Tool

- The Deep Agent decides when exact computation is needed.
- The tool executes Python in E2B and returns structured output.
- The model should use the tool for arithmetic, aggregations, rankings, statistics, parsing tabular data, and any exact numeric claim.

## Current Tool Shape

The current wrapper is intentionally small and adds only a few things on top of raw `Sandbox.run_code(...)`:

- structured JSON result
- optional file upload
- optional sandbox/context reuse
- stale-sandbox retry when a cached E2B sandbox has expired

## Practical Execution Rules

### File paths

There are always two path domains:

- local workspace path, for example `sample_data/expenses.csv`
- remote E2B path, for example `/home/user/input/01_expenses.csv`

The agent should be given the local workspace path.

The tool should upload that local file into E2B.

Python running inside E2B must read the remote uploaded path, not the original local path.

### Context reuse

If `reuse_context=True`, the same sandbox/context can be reused across calls.

Pros:

- faster follow-up calls
- notebook-like behavior
- variables and uploaded files can remain available

Cons:

- the sandbox can expire server-side while the local Python object still exists
- this creates stale handle errors on the next call

The wrapper already handles this by clearing the dead cached sandbox and retrying once with a fresh one.

### Reset behavior

If a clean environment is needed, use `reset_sandbox=True`.

This is the equivalent of "discard previous notebook state and start fresh."

## Recommended System Prompt Behavior

The agent should be told:

- use `execute_python_in_e2b` for deterministic computation
- do not do multi-step exact calculations in natural language
- when the user provides a local file path, pass it in the tool `files` argument
- after upload, use the remote uploaded path returned by the tool

If planning visibility is desired, also tell the agent to use the built-in `write_todos` tool for non-trivial tasks.

## Failure Model

### Sandbox expired or not found

Typical cause:

- a cached sandbox timed out on the E2B side

Handling:

- detect stale sandbox error
- clear cached sandbox/context
- create a fresh sandbox
- retry once

### File not found

Typical cause:

- the agent passed a remote E2B path as if it were a local workspace path

Handling:

- prompt with local workspace paths
- let the tool upload the file

### Tool works directly but agent flow fails

Typical cause:

- the agent did not pass `files=[...]`
- the agent tried to read the local file path inside E2B

Handling:

- verify the tool directly first
- then strengthen the agent system prompt

## When E2B Is a Good Fit

Use E2B when:

- you want hosted sandboxing
- you do not want to own container orchestration yet
- you want fast iteration on tool behavior
- you accept external sandbox lifecycle constraints

## Main Tradeoff

E2B reduces infrastructure work, but sandbox lifecycle is managed by a third party.

That means:

- less platform work for you
- less operational control for you

## Recommended Default

For this repo, the right default is:

- use E2B as a deterministic Python execution tool
- keep the wrapper small
- use session reuse only when it clearly helps
- keep recovery logic explicit and simple
