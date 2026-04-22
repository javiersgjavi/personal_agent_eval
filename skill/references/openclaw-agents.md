# OpenClaw Agents Reference

How to create, configure, and benchmark a custom OpenClaw agent with its own workspace and identity.

---

## What is an agent definition?

An agent definition is a directory under `configs/agents/<agent_id>/` containing two things:

1. **`agent.yaml`** — declares the agent ID, its openclaw config fragments (sandbox, model aliases), and metadata. The system prompt is generated from workspace files by default — do not override it unless you are intentionally testing a modified configuration.
2. **`workspace/`** — a template directory that is copied into an ephemeral folder before each run; this is what the agent sees as its home

The workspace is the agent's persistent context. It can contain instructions, memory structure, identity files, tool notes, and anything else that shapes how the agent behaves across tasks.

---

## `agent.yaml` schema

```yaml
schema_version: 1
agent_id: my_agent               # must match the directory name
title: My Agent
description: Optional summary.
tags: [custom, openclaw]

openclaw:
  identity:
    name: My Agent               # display name
  agents_defaults:
    sandbox: workspace-write     # workspace-write (default) or workspace-read
  agent:
    id: my-agent                 # ID passed to `openclaw agent --agent`
    # prompt: omit by default — see below
  model_defaults:
    aliases:
      default: benchmark-primary # alias used internally by the container
```

The `openclaw` block is merged into the generated `openclaw.json` config injected into the container. The `agent.id` value is passed to the `--agent` flag.

**Do not set `agent.prompt` by default.** The `prompt` field sets a `systemPromptOverride` that replaces OpenClaw's own internal system prompt — which is separate from the workspace files. The workspace files (`SOUL.md`, `IDENTITY.md`, `AGENTS.md`…) are context the agent reads, not the system prompt. Overriding the system prompt modifies the OpenClaw harness itself, so the benchmark is no longer evaluating the same agent that runs in production. Only set it if you specifically need to test a custom system prompt variant.

---

## Workspace files

These files are the agent's long-term memory and behavioural contract. The OpenClaw runtime loads them at session startup.

| File | Role | Required |
|---|---|---|
| `AGENTS.md` | Workspace rules, session startup flow, memory conventions, red lines | Recommended |
| `SOUL.md` | Personality, values, working principles | Optional |
| `IDENTITY.md` | Name, role, emoji, short bio | Optional |
| `USER.md` | Context about the person or system the agent works for | Optional |
| `TOOLS.md` | Environment-specific tool notes (SSH aliases, device names, etc.) | Optional |
| `BOOTSTRAP.md` | First-run setup instructions — deleted by the agent after first session | Optional |
| `HEARTBEAT.md` | How to respond when idle or in group contexts | Optional |

Missing standard files are filled with deterministic placeholder content by the harness. You can start with just `AGENTS.md` and add the others as you need them.

### `AGENTS.md`

This is the most important file. It sets the workspace contract: how sessions start, how memory works, what the agent is allowed to do without asking, and what requires confirmation. The agent reads it on startup unless the runtime has already injected the context.

A minimal `AGENTS.md`:
```markdown
# AGENTS.md

This folder is your workspace. Treat it that way.

## Memory
Daily notes: `memory/YYYY-MM-DD.md`
Long-term: `MEMORY.md`

## Red lines
- Don't send anything externally without confirming first.
- Ask before destructive operations.
```

### `SOUL.md`

Shapes how the agent communicates. Without it the agent defaults to a generic assistant voice. With it you can set a specific tone — concise, curious, formal, casual — and values like "be resourceful before asking".

### `IDENTITY.md`

Name and role. Useful when the agent needs to introduce itself or maintain a consistent persona across sessions.

### `USER.md`

Context about who the agent is working for: name, preferences, working style, timezone. This allows the agent to adapt its responses to the specific person rather than acting generically.

### `TOOLS.md`

Environment-specific notes that don't belong in skills: SSH host aliases, camera names, device nicknames, preferred voices. Keep it separate from `SOUL.md` so you can update tool notes without touching personality.

### `BOOTSTRAP.md`

Instructions run exactly once on first session. Typical contents: "Figure out who you are, set up your memory files, then delete this file." The agent deletes it after completing the setup.

---

## Creating your own agent

### Option 1: Start from scratch

```bash
mkdir -p configs/agents/my_agent/workspace
```

Create `configs/agents/my_agent/agent.yaml` and at minimum `workspace/AGENTS.md`. Start simple — you can add more workspace files as you understand what the agent needs.

### Option 2: Capture from a live OpenClaw instance

If you have an existing OpenClaw deployment with a configured workspace, you can capture it:

```bash
# inside the container or from the host
openclaw onboard --output configs/agents/my_agent/workspace/
```

This produces the standard workspace files populated with the agent's actual configuration. The `basic_agent` in this repo was captured this way from `ghcr.io/openclaw/openclaw:2026.4.15`.

### Option 3: Copy and modify an existing agent

```bash
cp -r configs/agents/basic_agent configs/agents/my_agent
# edit configs/agents/my_agent/agent.yaml and workspace files
```

Change `agent_id`, `title`, and the workspace contents to match your agent's identity and context.

---

## Wiring the agent into a run profile

```yaml
# configs/run_profiles/my_run.yaml
schema_version: 1
run_profile_id: my_run
title: My OpenClaw run
openclaw:
  agent_id: my_agent
  image: ghcr.io/openclaw/openclaw:2026.4.15
  timeout_seconds: 300
  docker_cli: docker          # optional, defaults to "docker"
execution_policy:
  max_concurrency: 1
  run_repetitions: 1
```

Then run:

```bash
uv run pae run-eval \
  --suite my_suite \
  --run-profile my_run \
  --evaluation-profile judge_gpt54_mini
```

---

## Fingerprinting and workspace changes

The agent fingerprint is a SHA-256 hash of the full `agent.yaml` and every file in `workspace/`. Changing any workspace file — even a comment in `AGENTS.md` — invalidates all stored runs for that agent. The next campaign re-executes all cases from scratch.

This is intentional: the workspace is part of the execution inputs, and changing it means the previous results are no longer reproducible from the current agent definition.

To make small edits without re-running everything, create a new agent ID (e.g., `my_agent_v2`) so both versions coexist in the output history.

---

## OpenClaw-specific run artifacts

For every openclaw case, the run directory contains a `run_1.artifacts/` folder with:

| File | Contents |
|---|---|
| `openclaw_config--openclaw.json` | The generated OpenClaw config injected into the container |
| `openclaw_workspace_diff--workspace.diff` | Unified diff of what the agent changed vs. the template |
| `openclaw_key_output_1--<filename>` | The extracted expected artifact (from `context.openclaw.expected_artifact`) |
| `openclaw_logs--openclaw.log` | Append-only log of all openclaw CLI commands and their exit codes |
| `openclaw_raw_trace--raw_session_trace.json` | Full stdout/stderr from the container, as parsed JSON |
| `openclaw_workspace_snapshot--workspace_snapshot.tar.gz` | Complete workspace state after the run |

**The most useful file for debugging an openclaw run** is `openclaw_workspace_diff--workspace.diff`. It shows exactly what the agent produced relative to the template:

```diff
--- template/report.md
+++ workspace/report.md
@@ -0,0 +1,3 @@
+# Tool Example
+2026-04-22
+openclaw-tool-example
```

If the expected artifact is missing from the diff, the agent did not produce it — regardless of what it said in the final response.
