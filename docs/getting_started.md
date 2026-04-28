# Getting Started

This guide walks you from a fresh checkout to a running benchmark in about five minutes.

---

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) installed
- An **OpenRouter API key** (used for both the subject model and the judge)
- **Docker** — only required for `openclaw` runs; not needed for `llm_probe`

---

## Install

```bash
# clone the repo
git clone <repo-url>
cd benchmark-openclaw-llm

# install all dependencies (including dev tools)
uv sync --group dev
```

---

## Set your API key

The CLI loads `.env` from the repository root automatically:

```bash
# .env
OPENROUTER_API_KEY=sk-or-v1-...
```

Or export it directly:

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
```

---

## Run the llm_probe example

The repository ships a ready-to-run `llm_probe` campaign:

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

This single command:

1. **Runs** two test cases against `minimax/minimax-m2.7` via OpenRouter
2. **Evaluates** each result with a GPT-5.4-mini judge
3. **Reports** scores, latency, and cost to the terminal
4. **Writes** a score-vs-cost chart PNG to `outputs/charts/`

The terminal output looks like:

```
Suite:             llm_probe_examples
Run profile:       llm_probe_examples
Evaluation:        judge_gpt54_mini
Run cost:          $0.0003
Evaluation cost:   $0.0018
Total cost:        $0.0021

MODEL          CASE                          RUN   EVAL  SCORE  LATENCY_S  TOTAL_COST
─────────────  ────────────────────────────  ────  ────  ─────  ─────────  ──────────
minimax_m27    llm_probe_tool_example        exec  exec   8.50      12.3    $0.001
minimax_m27    llm_probe_browser_example     exec  exec   7.00       9.1    $0.001
```

---

## Understand the output files

After the run, four kinds of files appear under `outputs/`:

```text
outputs/
├── charts/
│   └── judge_gpt54/
│       └── score_cost.png              ← score vs cost bubble chart
├── runs/
│   └── suit_llm_probe_examples/
│       └── run_profile_<fp6>/
│           └── minimax_m27/
│               └── llm_probe_tool_example/
│                   ├── run_1.json                   ← raw run trace + token usage
│                   └── run_1.fingerprint_input.json ← what was hashed
└── evaluations/
    └── suit_llm_probe_examples/
        └── evaluation_profile_<fp6>/
            └── eval_profile_judge_gpt54_<fp6>/
                └── minimax_m27/
                    └── llm_probe_tool_example/
                        ├── evaluation_result_summary_1.md  ← start here
                        ├── judge_1.prompt.debug.md         ← exact prompt shown to the judge
                        └── raw_outputs/
                            ├── final_result_1.json         ← hybrid score breakdown
                            ├── judge_1.json                ← raw judge response
                            └── judge_1.prompt.user.json    ← structured judge payload
```

**Start reading from `evaluation_result_summary_1.md`** — it is a human-readable Markdown file with the score, the judge's evidence, and the dimension breakdown.

To see exactly what the judge saw, open `judge_1.prompt.debug.md`.

---

## Run the OpenClaw example

OpenClaw evaluates a full autonomous agent. It requires Docker and a container image pull:

```bash
uv run pae run-eval \
  --suite openclaw_examples \
  --run-profile openclaw_examples \
  --evaluation-profile judge_gpt54_mini
```

The framework:

1. Materializes an ephemeral workspace from `configs/agents/basic_agent/`
2. Generates a per-run `openclaw.json` config file in that workspace
3. Invokes `docker run ghcr.io/openclaw/openclaw:2026.4.15 openclaw ...`
4. Captures the workspace diff, logs, and key outputs as evidence
5. Evaluates them through the same deterministic + judge pipeline

→ See [Minimal OpenClaw example](examples/minimal_openclaw.md) for the full layout.

---

## What happens on the second run?

Run the same command again:

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

The `RUN` and `EVAL` columns now show `reuse` instead of `exec`. No tokens were spent. The framework compared the stored fingerprints with the current config and found exact matches.

This is the fingerprint reuse system. → [Read how fingerprints work](fingerprints.md)

---

## Core mental model

Four YAML files define a complete benchmark campaign:

| File | Answers |
|---|---|
| `configs/cases/<id>/test.yaml` or `configs/cases/<group>/<id>/test.yaml` | What to test |
| `configs/suites/<id>.yaml` | Which cases and which models |
| `configs/run_profiles/<id>.yaml` | How to execute (temperature, retries, repetitions…) |
| `configs/evaluation_profiles/<id>.yaml` | How to judge and aggregate scores |

You can mix and match: the same case can appear in multiple suites, the same suite can be evaluated with different judge profiles, and the same run profile can be reused across suites.

→ [Config model](config_model.md) — visual diagram of how they fit together

---

## Next steps

- [Concepts](concepts.md) — scoring dimensions, judge-first evaluation, and reuse
- [Configuration reference](configuration.md) — complete YAML field reference
- [CLI reference](cli.md) — all `pae` commands and flags
- [Fingerprints & reuse](fingerprints.md) — how to force a re-run, what changes a fingerprint
- [Runnable examples](examples/runnable_examples.md) — walk through the shipped configs
