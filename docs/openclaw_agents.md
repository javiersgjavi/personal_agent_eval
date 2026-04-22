# OpenClaw Agents

How to configure a reusable OpenClaw agent with its own workspace — and use it to benchmark your own autonomous agent, not just the shipped example.

---

## What is an agent definition?

An agent definition is a directory under `configs/agents/<agent_id>/` containing two things:

- **`agent.yaml`** — declares the agent ID and its OpenClaw config fragments (sandbox, model aliases, optional system prompt override)
- **`workspace/`** — a template directory that is copied into an ephemeral folder before each run; this is what the agent sees as its home workspace

The workspace is the agent's persistent context. It carries instructions, identity, memory structure, tool notes, and anything else that shapes how the agent behaves. You define it once; the harness injects it into every run.

---

## Directory layout

```
configs/agents/my_agent/
  agent.yaml
  workspace/
    AGENTS.md         ← workspace rules, session startup, memory conventions
    SOUL.md           ← agent personality and values
    IDENTITY.md       ← name, role, description
    USER.md           ← context about the person or system the agent works for
    TOOLS.md          ← environment-specific tool notes
    BOOTSTRAP.md      ← first-run instructions (deleted by the agent after first session)
    HEARTBEAT.md      ← idle and group-context behaviour
```

Not all files are required. The harness fills in missing standard files with deterministic placeholder content. Start with `AGENTS.md` and add the others as your agent evolves.

---

## `agent.yaml`

```yaml
schema_version: 1
agent_id: my_agent                   # must match the directory name
title: My Agent
description: Optional description.
tags: [custom, openclaw]

openclaw:
  identity:
    name: My Agent
  agents_defaults:
    sandbox: workspace-write         # workspace-write (default) or workspace-read
  agent:
    id: my-agent                     # ID passed to `openclaw agent --agent`
    # prompt: omit this field — see note below
  model_defaults:
    aliases:
      default: benchmark-primary
```

The `openclaw` block is merged into the `openclaw.json` config injected into the container. The `agent.id` value is passed to the `--agent` flag of the `openclaw` CLI inside the container.

!!! warning "Do not set `agent.prompt` unless you intend to test a modified configuration"
    The `agent.prompt` field sets a `systemPromptOverride` in the generated `openclaw.json`, replacing OpenClaw's own internal system prompt. **Omitting it is the correct default.**

    OpenClaw ships with its own built-in system prompt that is separate from the workspace files (`SOUL.md`, `IDENTITY.md`, etc.). Those files are context the agent reads, not the system prompt itself. Overriding the system prompt via `agent.prompt` changes the OpenClaw harness and means you are no longer running the same agent that is deployed in production. The benchmark cannot reproduce real-world behaviour if the harness has been modified.

    Only set `agent.prompt` if you specifically want to benchmark the effect of a custom system prompt variant.

---

## Workspace files

### `AGENTS.md` — the most important file

Sets the workspace contract: how the agent starts a session, how memory is structured, what it can do freely, and what requires user confirmation. The OpenClaw runtime loads it at startup.

```markdown
# AGENTS.md

This folder is your workspace. Treat it that way.

## Memory
Daily notes: `memory/YYYY-MM-DD.md`
Long-term: `MEMORY.md`

## Red lines
- Don't send anything externally without confirming first.
- Ask before destructive operations.
- `trash` > `rm`
```

### `SOUL.md` — personality and values

Shapes how the agent communicates. Without it the agent defaults to a generic assistant voice. With it you can set tone (concise, curious, direct), working principles ("be resourceful before asking"), and trust rules.

### `IDENTITY.md` — name and role

Name, role description, emoji. Used when the agent needs to introduce itself or maintain a persona across sessions.

### `USER.md` — who the agent works for

Context about the person or system on the other end: name, preferences, working style, timezone. Allows the agent to adapt rather than act generically.

### `TOOLS.md` — environment-specific notes

SSH host aliases, camera names, device nicknames, preferred voices. Kept separate from `SOUL.md` so you can update tool notes without touching personality.

### `BOOTSTRAP.md` — first-run setup

Instructions executed exactly once on first session. Typical use: "Figure out who you are, set up your memory files, then delete this file." The agent deletes it after completing setup.

### `HEARTBEAT.md` — idle and group context

How the agent behaves when idle or participating in group chats — when to respond, when to stay silent, when to react.

---

## Creating an agent

### From scratch

```bash
mkdir -p configs/agents/my_agent/workspace
```

Create `agent.yaml` and at minimum `workspace/AGENTS.md`. Run a benchmark to verify behaviour, then expand the workspace as needed.

### From a live OpenClaw instance

If you have an existing OpenClaw deployment, capture its workspace directly:

```bash
openclaw onboard --output configs/agents/my_agent/workspace/
```

This produces the standard workspace files populated with the agent's actual configuration. The `basic_agent` in this repo was captured this way from `ghcr.io/openclaw/openclaw:2026.4.15`.

### From an existing agent

```bash
cp -r configs/agents/basic_agent configs/agents/my_agent
# update agent_id in agent.yaml and edit workspace files
```

---

## Wiring the agent into a campaign

Reference the agent in the run profile with `openclaw.agent_id`:

```yaml
# configs/run_profiles/my_run.yaml
schema_version: 1
run_profile_id: my_run
title: My OpenClaw run
openclaw:
  agent_id: my_agent                              # → configs/agents/my_agent/
  image: ghcr.io/openclaw/openclaw:2026.4.15      # pinned image
  timeout_seconds: 300
  docker_cli: docker                              # optional, defaults to docker
execution_policy:
  max_concurrency: 1
  run_repetitions: 1
  fail_fast: true
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

The agent fingerprint is a SHA-256 hash of `agent.yaml` and every file in `workspace/`. Changing any workspace file — including a comment in `AGENTS.md` — invalidates all stored runs for that agent. The next campaign re-executes all cases from scratch.

This is intentional: the workspace is part of the execution inputs, and changing it means previous results are no longer reproducible from the current agent definition.

!!! tip "Versioning agents"
    To keep results from multiple agent versions in the same `outputs/` tree, use distinct agent IDs (e.g. `my_agent_v1`, `my_agent_v2`). Each gets its own fingerprint-scoped directory so both histories coexist.

---

## OpenClaw run artifacts

For every openclaw case, the run directory contains a `run_1.artifacts/` folder alongside `run_1.json`:

```
outputs/runs/suit_<id>/run_profile_<fp>/<model>/<case>/
  run_1.json
  run_1.fingerprint_input.json
  run_1.artifacts/
    openclaw_config--openclaw.json              ← generated container config
    openclaw_workspace_diff--workspace.diff     ← what the agent changed
    openclaw_key_output_1--<filename>           ← extracted expected artifact
    openclaw_logs--openclaw.log                 ← append-only CLI command log
    openclaw_raw_trace--raw_session_trace.json  ← full container stdout/stderr
    openclaw_workspace_snapshot--*.tar.gz       ← complete workspace after the run
```

**The most useful file for debugging** is `openclaw_workspace_diff--workspace.diff`. It shows exactly what the agent produced relative to the template:

```diff
--- template/report.md
+++ workspace/report.md
@@ -0,0 +1,3 @@
+# Tool Example
+2026-04-22
+openclaw-tool-example
```

If the expected artifact is missing from the diff, the agent did not produce it — regardless of what it said in the final response. The deterministic check `openclaw_workspace_file_present` verifies this programmatically.

---

## The shipped example: `basic_agent`

`configs/agents/basic_agent/` is a default-style OpenClaw workspace captured from `openclaw onboard` in `ghcr.io/openclaw/openclaw:2026.4.15`. It is intentionally generic — a starting point for testing any model against standard tasks.

The workspace files (`AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `TOOLS.md`, `BOOTSTRAP.md`, `HEARTBEAT.md`) are populated with fictional but realistic content so the example runs produce meaningful evaluations without requiring a real agent setup.

See [OpenClaw Walkthrough](examples/minimal_openclaw.md) to run the example campaign end to end.
