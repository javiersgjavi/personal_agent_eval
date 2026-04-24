# Runnable Examples

This repository ships two small example campaigns that are designed to be run as-is and used as starting points for your own benchmarks.

Both are intentionally minimal: one model, a small set of cases, one judge call per case.

For documentation purposes, the repository also commits regenerated artifacts for these two campaigns under `outputs/`. Treat them as example outputs that show the expected layout and reporting format for a real run.

---

## llm_probe campaign

Tests a raw LLM with tool access.

### Files

| File | Path |
|---|---|
| Tool case | `configs/cases/llm_probe_tool_example/test.yaml` |
| Browser case | `configs/cases/llm_probe_browser_example/test.yaml` |
| Suite | `configs/suites/llm_probe_examples.yaml` |
| Run profile | `configs/run_profiles/llm_probe_examples.yaml` |
| Evaluation profile | `configs/evaluation_profiles/judge_gpt54_mini.yaml` |

### Command

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

### What it costs (approximate)

- Run model: `minimax/minimax-m2.7` — very cheap
- Judge: `openai/gpt-5.4-mini` — 1 judge call per case
- Total: roughly $0.002–$0.005 for both cases

---

## OpenClaw campaign

Tests a full autonomous agent running in Docker.

### Files

| File | Path |
|---|---|
| Reusable agent | `configs/agents/basic_agent/` |
| Tool case | `configs/cases/openclaw_tool_example/test.yaml` |
| Browser case | `configs/cases/openclaw_browser_example/test.yaml` |
| Multiturn case | `configs/cases/openclaw_multiturn_example/test.yaml` |
| Suite | `configs/suites/openclaw_examples.yaml` |
| Run profile | `configs/run_profiles/openclaw_examples.yaml` |
| Evaluation profile | `configs/evaluation_profiles/judge_gpt54_mini.yaml` |

### Command

```bash
uv run pae run-eval \
  --suite openclaw_examples \
  --run-profile openclaw_examples \
  --evaluation-profile judge_gpt54_mini
```

### Prerequisites

- Docker with network access (to pull `ghcr.io/openclaw/openclaw:2026.4.15`)
- `OPENROUTER_API_KEY` set on the host (forwarded into the container)

---

## What gets written

After running either campaign, the `outputs/` directory contains:

```text
outputs/
├── charts/
│   └── judge_gpt54/
│       └── score_cost.png                       ← quality vs cost bubble chart
├── runs/
│   └── suit_<suite_id>/
│       └── run_profile_<fp6>/
│           └── <model_id>/
│               └── <case_id>/
│                   ├── run_1.json               ← raw run trace
│                   ├── run_1.artifacts/         ← OpenClaw evidence files (openclaw only)
│                   └── run_1.fingerprint_input.json
└── evaluations/
    └── suit_<suite_id>/
        └── evaluation_profile_<fp6>/
            └── eval_profile_judge_gpt54_<fp6>/
                └── <model_id>/
                    └── <case_id>/
                        ├── evaluation_result_summary_1.md   ← start here
                        ├── judge_1.prompt.debug.md          ← exact judge prompt
                        └── raw_outputs/
                            ├── final_result_1.json          ← structured final evaluation result
                            ├── judge_1.json                 ← raw judge response
                            └── judge_1.prompt.user.json     ← structured subject view
```

In this repository, the checked-in example artifacts live under the concrete example campaign paths:

- `outputs/runs/suit_llm_probe_examples/`
- `outputs/evaluations/suit_llm_probe_examples/`
- `outputs/runs/suit_openclaw_examples/`
- `outputs/evaluations/suit_openclaw_examples/`
- `outputs/charts/judge_gpt54/`

---

## Recommended reading order

After the run completes:

**1. Read `evaluation_result_summary_1.md`**

This is the human-readable verdict: the final score, the judge's overall evidence, and per-dimension scores.

**2. Open `judge_1.prompt.debug.md`**

This shows exactly what the judge saw: the task, the response, the tool activity, the deterministic check summary. If a score seems wrong, check here first.

**3. Open `raw_outputs/final_result_1.json`**

This is the structured `FinalEvaluationResult`. It keeps the judge scores, deterministic summaries, and final reported dimensions side by side so you can audit what the judge saw and what was reported.

**4. Open `run_1.json` (if needed)**

The raw `RunArtifact` with the full event trace, token usage, and provider metadata. Use it to debug runner-level issues.

---

## Second run: reuse in action

Run the same command again:

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

The terminal output now shows `reuse` in both the `RUN` and `EVAL` columns. No tokens are spent. The framework computes the expected fingerprint for each `(model, case, repetition)`, finds a matching artifact in `outputs/`, and loads it directly.

→ [Fingerprints & reuse](../fingerprints.md)

---

## Extending the examples

### Add a new case

1. Create `configs/cases/my_case/test.yaml`
2. Add `my_case` to `case_selection.include_case_ids` in the suite

The next run computes only the new case. Existing results are reused.

### Add a new model

1. Add an entry to `models:` in the suite YAML
2. Re-run — only the new model's cases are executed

### Increase repetitions

Set `run_repetitions: 3` in the run profile. The fingerprint changes (new directory), and all cases are re-run with 3 repetitions. Scores are averaged across repetitions in the report.

### Change the judge model

Edit `model:` in the evaluation profile. The evaluation fingerprint changes → a new `eval_profile_<fp6>` directory is created → all evaluations re-run with the new judge. Run artifacts are reused unchanged.
