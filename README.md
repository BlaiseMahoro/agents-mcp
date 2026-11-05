# Agents: research, plan, execute

Three agents you can switch on and off, usable from a chat UI or as an MCP server.

- **Research** searches the web (SearXNG, or Claude's built-in search) and reasons over sources.
- **Plan** turns a goal, plus any research in the chat, into a JSON plan of steps.
- **Execute** runs a plan's steps in a throwaway Docker container, with your chat's workspace mounted.

In the chat, **Auto** lets a coordinator decide which agent to call. Pick an agent below the message box to talk to it directly.

Models are set per agent. The default is open-source **Qwen3.5-9B in LM Studio**. Ollama and Claude are preconfigured alternatives, and you can switch any of them in Settings.

## Setup (macOS)

You need Docker Desktop, LM Studio, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
make setup                      # backend + frontend deps, sandbox image, SearXNG on :8888
lms get qwen/qwen3.5-9b --mlx   # or download it in LM Studio's UI
lms server start                # OpenAI-compatible server on :1234
make dev                        # API on :8000, chat UI on http://localhost:3000
```

The sidebar shows whether Docker, the sandbox image, SearXNG and each model server are reachable. The Settings drawer says how to fix anything that isn't.

To use Claude for an agent, set its provider to `claude` in Settings or `config.yaml`. That needs `ANTHROPIC_API_KEY` or `ant auth login`. For research, set **Web search** to *Built in* to use Claude's native search.

## How it fits together

```
frontend/ (Next.js)  ──REST + SSE──►  backend/src/agents_core/
                                        api/          FastAPI app
                                        mcp_server/   MCP server (stdio), same agents
                                        agents/       orchestrator · research · planner · executor
                                        providers/    anthropic.py · openai_compat.py (LM Studio / Ollama / vLLM)
                                        sandbox/      one Docker container per run
                                        store/        SQLite: chats, plans, runs, settings
config.yaml        providers, default model per agent, sandbox limits
data/              agents.db + workspaces/<chat id>/ (files plans create)
```

- **Switches:** they live in SQLite and are seeded from `config.yaml`. A switched-off agent can't be picked, Auto won't call it, and its MCP tool isn't registered.
- **Approval:** with *Ask before running plans* on, Auto stops at a **Run plan** button. Choosing the Execute agent and sending a message counts as approval.
- **Plans:** steps are `shell`, `write_file`, `read_file` and `llm_task`. They run in dependency order; `on_failure` decides whether to stop, and steps that depend on a failed step are skipped. You can edit steps before running.
- **Sandbox:** all steps of a run share one container, so a background server stays up for later steps. File paths can't leave the workspace. CPU, memory, network and timeout are set under `sandbox:` in `config.yaml`.

## MCP server

```bash
claude mcp add agents -- uv run --directory "$(pwd)/backend" agents-mcp
```

Tools: `research`, `create_plan`, `execute_plan`, `run_pipeline`, `list_agents`, `get_plan` and `list_plans`. Work done over MCP appears in the chat UI as an "MCP session" chat. The server reads the switches when it starts, so restart it after changing them.

## Tests

```bash
make test   # pytest; the Docker sandbox test is skipped if Docker isn't running
```

## Notes on small local models

Qwen3.5-9B handles the whole loop: it calls tools, produces valid JSON plans, and sees runs through. It still makes reasoning mistakes, though. It might pick an older version from a stale search result, or write a verification step that hides its own failure with `|| true`. Review plans before running them, or switch the plan agent to a larger model.

Things the app does to help local models:

- Plans are made in two passes: the model reasons in prose first, then writes JSON with thinking off.
- JSON schemas are adapted for LM Studio's grammar engine.
- Invalid JSON gets up to 2 retries.
- If a tool loop ends with an empty answer, the model is asked once more for its final answer.
