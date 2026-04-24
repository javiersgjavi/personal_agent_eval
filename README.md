# personal_agent_eval

**Reproducible benchmarks for LLMs and autonomous agents.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://opensource.org/licenses/MIT)

---

`personal_agent_eval` (`pae`) is an open evaluation framework that benchmarks both raw LLMs and full autonomous agents. It runs your test cases against any model or agent, scores the results using a combination of deterministic checks and an LLM judge, and stores every artifact so you can inspect, reproduce, or extend the evaluation at any time.

The key property: every run is identified by a SHA-256 fingerprint of its inputs. Re-running the same configuration reuses stored results instead of spending tokens again. Adding a new model or case to an existing campaign only runs what is missing, nothing already computed is touched.

**Agent-friendly by design.** This repo ships a `SKILL.md` at its root. Any AI agent with skill support (such as Openclaw or Claude Code) loads it automatically and can set up test cases, run benchmarks, read results, and configure custom OpenClaw agents from a plain-language description, no step-by-step instructions needed.

---

## Quick start

```bash
uv sync --group dev
export OPENROUTER_API_KEY=sk-or-v1-...

# Run the shipped llm_probe example (no Docker required)
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

Run it a second time. Every row prints `reuse` — no API calls made, no tokens spent.

---

## Two things it can benchmark

### LLMs with tool use — `llm_probe`

The direct path: send a prompt to any model on [OpenRouter](https://openrouter.ai/), optionally with tools (`exec_shell`, `write_file`, `read_file`, `web_search`), and score what comes back. No infrastructure required beyond an API key.

### Autonomous agents — `openclaw`

This is where things get interesting.

OpenClaw is an autonomous coding agent that runs inside a Docker container with its own workspace, tools, and decision loop — the way real agents work in production. Evaluating it is a different problem from evaluating an LLM: you need to examine what the agent *did*, not just what it *said*. Which files did it create? Does the workspace match the expected state? Did it complete the task without being asked twice?

`personal_agent_eval` handles the full lifecycle: it spins up the container with a pinned image, captures the workspace diff, extracts key output artifacts, and feeds everything into the same evaluation pipeline used for LLMs. The framework scores the agent on the same six dimensions as any other model — with deterministic checks verifying workspace state and the LLM judge assessing quality and process.

```yaml
# configs/cases/my_agent_case/test.yaml
runner:
  type: openclaw
input:
  messages:
    - role: user
      content: |
        Write a Python script that reads a CSV file and outputs summary statistics.
        Save it as analysis.py and confirm when done.
  context:
    openclaw:
      expected_artifact: analysis.py
expectations:
  hard_expectations:
    - text: Creates analysis.py in the workspace.
    - text: The script reads a CSV file and computes statistics.
deterministic_checks:
  - check_id: script-present
    dimensions: [task]
    declarative:
      kind: openclaw_workspace_file_present
      relative_path: analysis.py
      contains: import
```

OpenClaw cases can also model follow-up user messages. Use `input.turns` when the benchmark should run multiple user turns in the same OpenClaw session; the harness keeps the same workspace, state directory, and `--session-id` across turns:

```yaml
runner:
  type: openclaw
input:
  messages:
    - role: system
      content: Keep context across user turns.
  turns:
    - role: user
      content: Create draft.md with a first version.
    - role: user
      content: Now revise draft.md and save the final answer as report.md.
  context:
    openclaw:
      expected_artifact: report.md
```

```bash
uv run pae run-eval \
  --suite openclaw_examples \
  --run-profile openclaw_examples \
  --evaluation-profile judge_gpt54_mini
```

Both runner modes share the same config schema, the same scoring pipeline, and the same output format.

### Bringing your own agent

The shipped examples use `basic_agent`, a default-style OpenClaw workspace. To benchmark your own agent, create a directory under `configs/agents/<agent_id>/` with an `agent.yaml` and a `workspace/` folder containing the files that define the agent's identity, memory contract, working context (`AGENTS.md`, `SOUL.md`, `USER.md`, etc.), and skills. Point your run profile at it with `openclaw.agent_id: my_agent` and run normally.

The workspace is copied into an ephemeral container directory before each run — the agent sees it as home. Changing any workspace file invalidates the fingerprint and triggers a fresh run, so your evaluation always reflects the current agent definition. See [docs/examples/minimal_openclaw.md](docs/examples/minimal_openclaw.md) for a full example.

---

## How it works

```
  test cases + suite
        │
        ▼
    pae run     ──→  RunArtifact  (trace, tool calls, token usage, workspace diff)
        │
        ▼
  deterministic ──→  per-check pass/fail  (no LLM, always stable)
   evaluation
        │
        ▼
     judge      ──→  6-dimension scores + evidence  (LLM judge via OpenRouter)
        │
        ▼
  aggregation   ──→  FinalEvaluationResult  (hybrid score 0–10)
        │
        ▼
  reporting     ──→  terminal tables · JSON · PNG chart
```

The deterministic and judge layers are independent. Changing the judge model re-evaluates without re-running the model. Changing a run parameter re-runs without touching evaluations from other configurations.

---

## Scoring

Every case is scored on six dimensions (0–10 scale):

| Dimension | What it measures |
|---|---|
| `task` | Did the output fulfill the stated goal? |
| `process` | Was the approach sound? Right tools, constraints respected, no hallucinations. |
| `autonomy` | Independent operation — sensible decisions, no over-asking. |
| `closeness` | Does the response resemble what a skilled human would produce? |
| `efficiency` | Achieved the goal without unnecessary noise or extra steps. |
| `spark` | Something noteworthy — an elegant shortcut, a useful insight. |

The `final_score` is the judge's holistic verdict, not a weighted average. Per-dimension scores exist to tell you *why* a model scored the way it did.

Scores combine two layers:

- **Deterministic checks** — file existence, content matching, tool call counts. Fast, free, always stable.
- **LLM judge** — flexible evaluation of anything deterministic checks cannot capture.

Deterministic checks are informative evidence for the judge. The final score and per-dimension scores come from the judge.

---

## Everything is auditable

Every artifact is a plain file you can inspect directly:

```
outputs/
├── runs/suit_<id>/run_profile_<fp>/
│   └── <model>/<case>/
│       ├── run_1.json                     ← full trace: every message, tool call, token count
│       └── run_1.fingerprint_input.json   ← exact inputs that produced this run
└── evaluations/suit_<id>/evaluation_profile_<fp>/eval_profile_<id>_<fp>/
    └── <model>/<case>/
        ├── evaluation_result_summary_1.md ← human-readable verdict, start here
        ├── judge_1.prompt.debug.md        ← the exact prompt the judge received
        └── raw_outputs/
            ├── final_result_1.json        ← judge scores + deterministic summaries
            └── judge_1.json              ← raw judge response
```

If a score seems wrong, `judge_1.prompt.debug.md` shows exactly what the judge saw. If the run looks wrong, `run_1.json` has the full trace.

---

## Configuration

Everything is YAML. No code required to add test cases, models, or campaigns.

```
configs/
  cases/<case_id>/test.yaml          ← what to test
  suites/<suite_id>.yaml             ← which cases × which models
  run_profiles/<id>.yaml             ← temperature, retries, timeouts
  evaluation_profiles/<id>.yaml      ← judge model, aggregation policy
  agents/<agent_id>/agent.yaml       ← reusable OpenClaw agent definition
```

Flag values can be IDs or explicit paths — `--suite my_suite` resolves to `configs/suites/my_suite.yaml` automatically.

---

## Documentation

| Topic | Link |
|---|---|
| Getting started | [docs/getting_started.md](docs/getting_started.md) |
| Concepts: fingerprints, scoring, runner modes | [docs/concepts.md](docs/concepts.md) |
| Full config reference | [docs/configuration.md](docs/configuration.md) |
| CLI reference | [docs/cli.md](docs/cli.md) |
| Deterministic checks | [docs/deterministic_checks.md](docs/deterministic_checks.md) |
| Hybrid evaluation and scoring | [docs/hybrid_evaluation.md](docs/hybrid_evaluation.md) |
| Run artifacts | [docs/run_artifacts.md](docs/run_artifacts.md) |
| Shipped runnable examples | [docs/examples/runnable_examples.md](docs/examples/runnable_examples.md) |

Browse the full docs locally:

```bash
uv sync --group docs
uv run mkdocs serve
```

---

## Requirements

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) for environment management
- An [OpenRouter](https://openrouter.ai/) API key (`OPENROUTER_API_KEY`)
- Docker — only required for `openclaw` runs

---

## Contributing

This is a public library. Every module is a self-contained layer with explicit inputs and outputs — the code is meant to be read.

If you want to add a deterministic check, a new runner mode, or a runnable example campaign, open an issue or a PR. The test suite runs without any API keys or Docker:

```bash
uv sync --group dev
uv run pre-commit install
uv run pytest
```

Before committing, the local hook will auto-format staged Python files with `ruff format`, apply safe lint fixes with `ruff check --fix`, and scan staged files for leaked secrets. To run the same checks manually across the repo:

```bash
uv run pre-commit run --all-files
```
