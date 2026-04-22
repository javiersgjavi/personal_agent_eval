# personal_agent_eval

`personal_agent_eval` is an open evaluation framework for LLM and agent-based systems. It is designed to be clear, reproducible, and easy to extend — whether you are a developer benchmarking a model for the first time or an agent consuming structured evaluation data.

---

## What does it do?

It takes a set of **test cases** (what to ask), a **model or agent** (who to ask), and an **evaluation policy** (how to judge the answer), and produces a structured, reproducible score.

Every run is:

- **Reproducible** — a SHA-256 fingerprint tracks exactly what was executed. Re-running the same configuration reuses the stored result instead of spending tokens again.
- **Transparent** — every artifact is a plain JSON or Markdown file you can inspect directly: the run trace, the judge's exact prompt, the score breakdown, the cost split.
- **Incremental** — adding a new case or a new model to a campaign only runs the missing combinations. Nothing already computed is touched.

---

## Two runner modes

| Mode | What gets evaluated | How it runs |
|---|---|---|
| `llm_probe` | A raw LLM completion endpoint with optional tool use | Direct HTTP call to OpenRouter |
| `openclaw` | A full autonomous agent running inside a Docker container | `docker run` with the pinned OpenClaw image |

Both modes share the same config schema, the same evaluation pipeline, and the same output format.

---

## The evaluation pipeline

```
  test cases + suite
        │
        ▼
    pae run      ──→  RunArtifact (raw trace, token usage, tool calls)
        │
        ▼
  deterministic  ──→  per-check pass/fail  (no LLM, always stable)
   evaluation
        │
        ▼
    judge        ──→  6-dimension scores + evidence  (LLM judge via OpenRouter)
        │
        ▼
  aggregation    ──→  FinalEvaluationResult  (hybrid score 0–10)
        │
        ▼
   reporting     ──→  terminal tables · JSON · optional PNG chart
```

---

## Quick start

```bash
# install
uv sync --group dev

# set your OpenRouter API key
export OPENROUTER_API_KEY=sk-or-...

# run the shipped llm_probe example campaign
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

→ [Full getting started guide](getting_started.md)

---

## Documentation map

| I want to… | Go to |
|---|---|
| Run my first benchmark | [Getting started](getting_started.md) |
| Understand the 4 config files | [Config model](config_model.md) |
| See the shipped example configs | [Runnable examples](examples/runnable_examples.md) |
| Write my own test cases | [Configuration reference](configuration.md) |
| Understand how scores work | [Concepts](concepts.md) |
| Understand fingerprints and reuse | [Fingerprints & reuse](fingerprints.md) |
| Use the CLI effectively | [CLI reference](cli.md) |
| Debug a specific evaluation | [Judge results](judge_results.md) |
| Understand the output files | [Run artifacts](run_artifacts.md) |

---

## Repository layout

```text
configs/          ← your YAML configs: cases, suites, run profiles, eval profiles, agents
src/              ← Python source (personal_agent_eval package)
tests/            ← pytest test suite (203 tests, all mocked)
docs/             ← this documentation
outputs/          ← generated at runtime; not committed to git
```

---

!!! tip "Open source"
    This is a public library. If you find a bug, want to add a deterministic check, or
    have a new example campaign to contribute, open an issue or PR. Every module is a
    self-contained layer with explicit inputs and outputs — the code is meant to be read.
