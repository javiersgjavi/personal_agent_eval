# Concepts

This page explains the core ideas behind `personal_agent_eval` — what it measures, why it is designed the way it is, and how the pieces fit together.

---

## What is being evaluated?

Every test case asks a model or agent to do something, then measures:

1. **Did it do the right thing?** (task completion)
2. **Did it do it the right way?** (process quality)
3. **How much did it help beyond the basics?** (autonomy, closeness, efficiency, spark)

These are captured as six scoring dimensions on a 0–10 scale.

---

## The six dimensions

| Dimension | What it measures |
|---|---|
| `task` | Whether the output fulfills the stated goal — correct content, correct files, correct format |
| `process` | Whether the agent followed a sound approach — used the right tools, respected constraints, didn't hallucinate steps |
| `autonomy` | Whether the agent operated independently — made sensible decisions without over-asking or hand-holding |
| `closeness` | Whether the output matched what a good human response would look like — tone, framing, completeness |
| `efficiency` | Whether the agent achieved the goal with reasonable resource use — no unnecessary tool calls, no verbose noise |
| `spark` | Whether the response showed something noteworthy — useful insight, elegant shortcut, thoughtful initiative |

These dimensions are scored by the judge and, where possible, grounded by deterministic checks.

!!! note "Final score"
    The `final_score` (0–10) comes from the judge's overall assessment (`judge_overall.score`), not from a weighted average of the six dimensions. The dimensions are there for diagnosis — to understand *where* a model is strong or weak. The overall score is the judge's holistic verdict after reviewing all evidence.

---

## Two evaluation layers

### Deterministic layer

Runs directly against the stored `RunArtifact` — no LLM required. Examples:

- Did the final response exist? (`final_response_present`)
- Was the right file created? (`file_contains`)
- Was the tool called the expected number of times? (`tool_call_count`)

These checks are fast, stable, and free. They produce hard pass/fail signals that the aggregator can use to cap or adjust the judge scores.

### Judge layer

An LLM judge (configured in the evaluation profile) reads a compact, structured view of the run and scores each dimension. The judge sees:

- the original task (messages + expectations)
- the final response
- the tool activity summary
- key generated artifacts (for OpenClaw runs)
- the deterministic check summary

The judge does **not** see internal infrastructure details (run IDs, container image names, file paths, raw provider metadata). The prompt is designed to surface only what matters for evaluation.

The exact prompt sent to the judge is persisted as `judge_1.prompt.debug.md` next to the evaluation results, so you can always audit what was evaluated and how.

---

## Hybrid aggregation

The final score combines both layers according to the `evaluation_profile.yaml`:

```yaml
final_aggregation:
  default_policy: judge_only        # default: judge score drives everything
  dimensions:
    process:
      policy: weighted
      judge_weight: 0.9
      deterministic_weight: 0.1    # nudge process score with deterministic evidence
```

Three dimension policies are available:

| Policy | How the final dimension score is computed |
|---|---|
| `judge_only` | Takes the judge score as-is |
| `deterministic_only` | Takes the deterministic score (0 or 10) only |
| `weighted` | `(judge × judge_weight) + (deterministic × deterministic_weight)` |

If a deterministic check fails a hard expectation, the aggregator can cap the score regardless of the judge's assessment.

→ [Hybrid evaluation](hybrid_evaluation.md) — detailed policy reference

---

## Runner types

### llm_probe

`llm_probe` sends the test case input directly to a model via OpenRouter and orchestrates a tool-use loop. It is the simplest runner: one API call (or a few for multi-turn tool use), one `RunArtifact`.

Tools available: `exec_shell`, `read_file`, `write_file`, `web_search` (and others configured in `input.context.llm_probe.tools`).

### openclaw

`openclaw` runs a full autonomous agent inside a pinned Docker container. The framework:

1. Copies a workspace template from `configs/agents/<agent_id>/workspace/`
2. Generates a `openclaw.json` config in the workspace
3. Invokes the container: `docker run <image> openclaw agent run ...`
4. Captures the workspace diff, logs, key output files, and session trace as evidence
5. Evaluates the evidence through the same deterministic + judge pipeline

This lets you benchmark real agent behavior — including multi-step planning, file creation, error recovery — in a reproducible, sandboxed environment.

---

## Incremental campaigns

A **campaign** is the combination of a suite, a run profile, and the models in that suite. Campaigns are stored under `outputs/` with paths derived from the suite ID and a fingerprint of the run profile.

When you run the same campaign twice, the framework checks the stored fingerprint for each `(model, case, repetition)` combination. If it matches, that result is reused. If it does not, only that combination is re-executed.

This means you can:

- Add a new case to a suite without re-running existing cases
- Increase `run_repetitions` and only the new repetitions are run
- Change `temperature` and get a new fingerprint → new directory → all cases re-run (but old results preserved)

→ [Fingerprints & reuse](fingerprints.md)

---

## Repetitions

Both runs and evaluations support repetitions:

- **`run_repetitions`** (in `run_profile.yaml`) — how many times to execute each case. Useful for measuring model consistency. Each repetition is stored as a separate `run_N.json`.
- **`judge repetitions`** (in `evaluation_profile.yaml`) — how many times to call the judge per case. Scores are aggregated (typically median) across successful iterations.

When multiple run repetitions exist, the workflow takes the mean `final_score` across them before reporting.

---

## Cost tracking

Every run and evaluation records token usage and estimated USD cost. The CLI reports:

- `RUN_COST` — tokens spent by the subject model
- `EVAL_COST` — tokens spent by the judge
- `TOTAL_COST` — sum of both

The structured JSON output also includes per-model and per-suite totals. This makes it easy to compare models not just on quality but on quality-per-dollar.
