# Hybrid Evaluation

Evaluation combines the **deterministic layer** (stable, pass/fail, free) with the **judge layer** (LLM-based, nuanced, 0–10) into a single `FinalEvaluationResult`.

The deterministic layer is informative. The judge reads that evidence and assigns the dimension scores and the final score.

---

## The final evaluation result

```json
{
  "schema_version": 1,
  "case_id": "llm_probe_tool_example",
  "run_id": "run_001",
  "deterministic_dimensions": {
    "task": 10.0,
    "process": 10.0
  },
  "judge_dimensions": {
    "task": 8.5,
    "process": 9.0,
    "autonomy": 8.0,
    "closeness": 8.5,
    "efficiency": 7.5,
    "spark": 6.0
  },
  "judge_overall": {
    "score": 8.5,
    "evidence": [
      "Used all required tools correctly",
      "File content matches the expected marker",
      "Confirmation was brief and accurate"
    ]
  },
  "final_dimensions": {
    "task": 8.5,
    "process": 9.0,
    "autonomy": 8.0,
    "closeness": 8.5,
    "efficiency": 7.5,
    "spark": 6.0
  },
  "final_score": 8.5,
  "summary": {
    "deterministic_passed_checks": 2,
    "deterministic_failed_checks": 0,
    "deterministic_error_checks": 0,
    "judge_successful_iterations": 1,
    "judge_failed_iterations": 0
  }
}
```

---

## final_score

`final_score` is **the judge's overall score** (`judge_overall.score`). It is the judge's holistic verdict after reviewing all evidence. It is not derived from the per-dimension scores.

The per-dimension `final_dimensions` scores exist for diagnostics: to understand where a model is strong or weak. They do not determine the top-level score in V1.

---

## Deterministic signals

Deterministic checks still produce per-dimension summaries. A check tagged with `dimensions: [task, process]` contributes evidence to both those dimensions. If the check passes the dimension gets 10.0; if it fails, 0.0. The deterministic dimension score is the average across all checks tagged to that dimension.

Check errors are excluded and generate a warning.

---

## Hard expectation failure

If a deterministic check that maps to `task` fails, that is strong evidence that the task was not completed and the judge sees it in the evaluation packet.

Hard expectations in `test.yaml` (`expectations.hard_expectations`) are presented to the judge as part of the evaluation target and influence the judge's own assessment, but they do not mechanically cap scores on their own.

---

## Aggregating repetitions

When `run_repetitions > 1`, the workflow runs each case multiple times and stores a separate `RunArtifact` and `FinalEvaluationResult` per repetition. The CLI and report aggregate them:

- `final_score` → mean of available scores across repetitions
- per-dimension scores → mean per dimension
- token usage and cost → sum across repetitions
- latency → mean across repetitions

This gives a more reliable estimate of model behaviour at the cost of additional token spend.

---

## Inspecting the result

The final result records three useful views side by side:

- `judge_dimensions` — the judge's 0–10 scores per dimension
- `deterministic_dimensions` — the deterministic summaries per dimension when checks are mapped there
- `final_dimensions` — the reported dimension scores, which mirror the judge scores

---

## Cost-quality tradeoff

Every `FinalEvaluationResult` is associated with a `UsageSummary` that records:

- `run_cost_usd` — cost of the subject run (model tokens)
- `evaluation_cost_usd` — cost of the judge calls
- `total_cost_usd` — sum of both

Use `pae report --output json` to get the structured breakdown, or look at the `TOTAL_COST` column in the terminal output. The optional score/cost PNG chart plots this relationship visually for all models in the campaign.

→ [Reporting](reporting.md)
