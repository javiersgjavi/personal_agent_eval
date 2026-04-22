# Minimal OpenClaw Example

This page walks through the shipped OpenClaw example campaign. For **installing and operating OpenClaw itself** (gateway, channels, global config), see the [official OpenClaw documentation](https://docs.openclaw.ai). This page covers only the benchmark harness.

---

## What this example tests

Two cases running a full autonomous agent inside Docker:

| Case | What it tests |
|---|---|
| `openclaw_tool_example` | Agent uses tools to create `report.md` with specific content |
| `openclaw_browser_example` | Agent uses browser/web search to find an official URL and writes `report.md` |

Both cases use `minimax/minimax-m2.7` as the agent model and `openai/gpt-5.4-mini` as the judge.

---

## Prerequisites

- **Docker** (or a compatible OCI runtime)
- `OPENROUTER_API_KEY` set on the host (forwarded to the container)
- Network access to pull `ghcr.io/openclaw/openclaw:2026.4.15`

The framework does **not** use `~/.openclaw/openclaw.json`. It generates a per-run `openclaw.json` in a temporary workspace directory, sets `OPENCLAW_STATE_DIR`, and invokes the `openclaw` CLI inside the pinned container image.

---

## File layout

| File | Path |
|---|---|
| Reusable agent | `configs/agents/basic_agent/` |
| Default-style bootstrap agent | `configs/agents/basic_agent/` |
| Tool case | `configs/cases/openclaw_tool_example/test.yaml` |
| Browser case | `configs/cases/openclaw_browser_example/test.yaml` |
| Suite | `configs/suites/openclaw_examples.yaml` |
| Run profile | `configs/run_profiles/openclaw_examples.yaml` |
| Evaluation profile | `configs/evaluation_profiles/judge_gpt54_mini.yaml` |

---

## Run it

```bash
# run only (requires Docker)
uv run pae run \
  --suite openclaw_examples \
  --run-profile openclaw_examples

# run and evaluate
uv run pae run-eval \
  --suite openclaw_examples \
  --run-profile openclaw_examples \
  --evaluation-profile judge_gpt54_mini
```

---

## The config files explained

### Suite — `configs/suites/openclaw_examples.yaml`

```yaml
schema_version: 1
suite_id: openclaw_examples
title: OpenClaw runnable examples
models:
  - model_id: minimax_m27
    requested_model: minimax/minimax-m2.7
    label: minimax/minimax-m2.7
case_selection:
  include_case_ids:
    - openclaw_tool_example
    - openclaw_browser_example
metadata:
  owner: qa
  agent: basic_agent
  run_profile: openclaw_examples
```

---

### Run profile — `configs/run_profiles/openclaw_examples.yaml`

```yaml
schema_version: 1
run_profile_id: openclaw_examples
title: OpenClaw runnable examples
openclaw:
  agent_id: basic_agent                            # → configs/agents/basic_agent/
  image: ghcr.io/openclaw/openclaw:2026.4.15       # pinned image
  timeout_seconds: 300
execution_policy:
  max_concurrency: 1
  run_repetitions: 1
  fail_fast: true
```

The `openclaw.agent_id` field points to the agent directory. The `image` field pins the container version — this is intentional; changing the image produces a new fingerprint and re-runs all cases.

---

### Agent — `configs/agents/basic_agent/agent.yaml`

```yaml
schema_version: 1
agent_id: basic_agent
title: Basic Agent
description: Default-style OpenClaw agent workspace captured from `openclaw onboard` in ghcr.io/openclaw/openclaw:2026.4.15.
openclaw:
  identity:
    name: Basic Agent
  agents_defaults:
    sandbox: workspace-write
  agent:
    id: basic-agent
    prompt: Follow the workspace files and behave like a default OpenClaw agent.
  model_defaults:
    aliases:
      default: benchmark-primary
```

This is the fragment that gets embedded into the generated `openclaw.json`. The `workspace/` directory contains template files that are copied into every ephemeral run workspace.

```text
configs/agents/basic_agent/workspace/
  AGENTS.md       ← default workspace guidance
  BOOTSTRAP.md    ← first-run onboarding note
  HEARTBEAT.md    ← heartbeat template
  IDENTITY.md     ← initialized example identity
  SOUL.md         ← default agent persona
  TOOLS.md        ← local notes template
  USER.md         ← initialized example user profile
```

This example now uses `configs/agents/basic_agent/`, which mirrors the default workspace created by `openclaw onboard` in `ghcr.io/openclaw/openclaw:2026.4.15`, with fictional `IDENTITY.md` and `USER.md` values filled in so the docs show an initialized agent instead of blank templates.

---

### Tool case — `configs/cases/openclaw_tool_example/test.yaml`

```yaml
schema_version: 1
case_id: openclaw_tool_example
title: OpenClaw tool example
runner:
  type: openclaw
input:
  messages:
    - role: user
      content: |
        Use real tools to create a file `report.md` in the workspace.
        The file must contain:
        - a title `# Tool Example`
        - a line with the current date obtained via a command
        - a literal line `openclaw-tool-example`
        At the end, briefly confirm that you created the file.
  context:
    openclaw:
      expected_artifact: report.md
expectations:
  hard_expectations:
    - text: Produces report.md in the workspace.
    - text: Includes the literal marker openclaw-tool-example in report.md.
rubric:
  version: 1
  scale:
    min: 0
    max: 10
    anchors:
      "10": report.md exists with all required lines; final response briefly confirms creation.
      "7": Mostly complete; minor formatting or clarity issues.
      "4": Missing required content or unclear confirmation.
      "0": No attempt / irrelevant / empty output.
  criteria:
    - name: Required artifact content
      what_good_looks_like: report.md contains the title, a date line from a command, and the marker.
      what_bad_looks_like: report.md missing or missing required lines.
    - name: Tool-grounded evidence
      what_good_looks_like: Uses tools to obtain the date and write the file.
      what_bad_looks_like: Claims file/date without evidence.
deterministic_checks:
  - check_id: openclaw-tool-example-final
    dimensions: [task]
    declarative:
      kind: final_response_present
  - check_id: openclaw-tool-example-report
    dimensions: [process]
    declarative:
      kind: openclaw_workspace_file_present
      relative_path: report.md
      contains: openclaw-tool-example
tags:
  - example
  - openclaw
  - tool_use
```

Key differences from `llm_probe`:
- `runner.type: openclaw`
- `input.context.openclaw.expected_artifact` — a hint to the harness about what output file to look for
- `openclaw_workspace_file_present` check — verifies the file exists in the workspace diff (not on the host filesystem)

---

### Browser case — `configs/cases/openclaw_browser_example/test.yaml`

```yaml
schema_version: 1
case_id: openclaw_browser_example
title: OpenClaw browser example
runner:
  type: openclaw
input:
  messages:
    - role: user
      content: |
        Use the browser or web search to find an official Python page about the current stable version.
        Create a `report.md` in the workspace with:
        - a title `# Browser Example`
        - the official URL you consulted
        - a short sentence justifying why that source is reliable
  context:
    openclaw:
      expected_artifact: report.md
expectations:
  hard_expectations:
    - text: Produces report.md in the workspace.
    - text: Includes an official Python URL in report.md.
deterministic_checks:
  - check_id: openclaw-browser-example-final
    dimensions: [task]
    declarative:
      kind: final_response_present
  - check_id: openclaw-browser-example-report
    dimensions: [process]
    declarative:
      kind: openclaw_workspace_file_present
      relative_path: report.md
      contains: python.org
tags:
  - example
  - openclaw
  - browser
  - web
```

The `contains: python.org` check verifies the workspace file references an actual Python.org URL, not just any URL.

---

## How the harness works

1. **Fingerprint check** — computes the run fingerprint (case + profile + agent + workspace content). If a matching artifact exists, reuses it.
2. **Workspace materialization** — copies the `workspace/` template into a fresh temp dir. Adds model configuration as `OPENROUTER_API_KEY`-aware aliases.
3. **Config generation** — writes `openclaw.json` in the workspace with the merged agent config and model routing.
4. **Docker execution** — runs `docker run --rm -v <workspace>:/work <image> openclaw agent run ...` with env vars forwarded.
5. **Evidence capture** — collects the workspace diff, logs, key output files, and raw session trace.
6. **RunArtifact** — all evidence is referenced from `runner_metadata.openclaw`. Large files are stored in `run_1.artifacts/` and referenced by `file://` URI.
7. **Evaluation** — the judge sees the final response, tool activity summary, and workspace artifacts. It does not see Docker internals or raw logs.

---

## What gets written to `outputs/`

The repository commits regenerated artifacts for this example campaign under `outputs/` as reference output, so the OpenClaw artifact layout is visible in git.

```text
outputs/
├── runs/
│   └── suit_openclaw_examples/
│       └── run_profile_<fp6>/
│           └── minimax_m27/
│               └── openclaw_tool_example/
│                   ├── run_1.json
│                   ├── run_1.artifacts/
│                   │   ├── openclaw.json         ← generated config
│                   │   ├── workspace.tar.gz      ← workspace snapshot
│                   │   ├── workspace.diff        ← what changed
│                   │   ├── openclaw.log          ← container logs
│                   │   └── report.md             ← key output file
│                   └── run_1.fingerprint_input.json
└── evaluations/
    └── suit_openclaw_examples/
        └── evaluation_profile_<fp6>/
            └── eval_profile_judge_gpt54_<fp6>/
                └── minimax_m27/
                    └── openclaw_tool_example/
                        ├── evaluation_result_summary_1.md
                        ├── judge_1.prompt.debug.md
                        └── raw_outputs/
                            ├── final_result_1.json
                            ├── judge_1.json
                            └── judge_1.prompt.user.json
```

The `run_1.artifacts/` directory contains all the evidence files. The `workspace.diff` shows exactly what the agent created or modified.

---

→ [Runnable examples](runnable_examples.md) — both campaigns and reading order
→ [Run artifacts](../run_artifacts.md) — OpenClaw evidence schema details
