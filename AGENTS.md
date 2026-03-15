# Repository Guidelines

## Project Structure & Module Organization
This repository is a minimal Python 3.12 project. The current entry point is [`main.py`](C:\Users\Sarthak Kaushik\Desktop\Playground2\Deepagent_lang\main.py), and package metadata lives in [`pyproject.toml`](C:\Users\Sarthak Kaushik\Desktop\Playground2\Deepagent_lang\pyproject.toml). Keep new application modules in a dedicated package directory once the codebase grows, for example `deepagent_lang/`, and place tests in a top-level `tests/` directory that mirrors the source layout.

## Build, Test, and Development Commands
Use Python 3.12, matching [`.python-version`](C:\Users\Sarthak Kaushik\Desktop\Playground2\Deepagent_lang\.python-version).

- `uv sync`: create a local environment from `pyproject.toml`.
- `uv run python main.py`: run the current CLI entry point.
- `python main.py`: simple fallback when `uv` is not installed.
- `python -m compileall main.py`: quick syntax check before opening a PR.

If dependencies or scripts are added later, document them in `pyproject.toml` and keep this section updated.

## Coding Style & Naming Conventions
Follow standard Python conventions: 4-space indentation, `snake_case` for functions and variables, `PascalCase` for classes, and short module names in lowercase. Prefer sAct like a high-performing senior engineer. Be concise, direct, decisive, and execution-focused.  

Solve problems with simple, maintainable, production-friendly solutions. Prefer low-complexity code that is easy to read, debug, and modify.  

Do not overengineer. Do not introduce heavy abstractions, extra layers, or large dependencies for small features. Choose the smallest solution that solves the problem well.  

Keep implementations clean, APIs small, behavior explicit, and naming clear. Avoid cleverness unless it clearly improves the outcome.  

Write code that another strong engineer can quickly understand, safely extend, and confidently ship.  

When learning new concepts, my aim is to build solid gut level intuition with concrete examples. Give me alternative views / perspective on the concept. Go for a comprehensive response, I don't mind details. Whenever you're explaining a difficult concept (like a formula), give concrete (simple) examples to help me understand. Also I would prefer if you ask questions or give problems to me check understanding (I don't want to learn passively, I know real understanding happens when you do exercises
 entry points for runnable modules. When formatting or linting tools are added, wire them through `pyproject.toml` and use them consistently across the repo.

## Testing Guidelines
There is no automated test suite checked in yet. Add new tests under `tests/` using `pytest`, with filenames like `test_main.py` and test names such as `test_prints_greeting`. For now, contributors should at minimum run the app locally and perform a syntax check before submitting changes.

## Commit & Pull Request Guidelines
The repository has no commit history yet, so use imperative, focused commit messages as the baseline convention, for example `Add CLI argument parsing` or `Create tests for startup flow`. Keep commits narrow in scope. Pull requests should include a short description, testing notes, and terminal output or screenshots when behavior changes are user-visible.

## Configuration Tips
Do not commit virtual environments, build artifacts, or bytecode; [`.gitignore`](C:\Users\Sarthak Kaushik\Desktop\Playground2\Deepagent_lang\.gitignore) already excludes them. Keep secrets out of the repository and prefer environment variables for future configuration.
