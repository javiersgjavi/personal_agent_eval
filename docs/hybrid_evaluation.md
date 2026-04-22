# Hybrid Evaluation

Hybrid evaluation combines the **deterministic layer** (stable, pass/fail, free) with the **judge layer** (LLM-based, nuanced, 0–10) into a single `FinalEvaluationResult`.

The combination is configurable per dimension: you can let the judge drive everything, rely only on deterministic checks, or blend both with explicit weights.

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
  "dimension_resolutions": {
    "task": {
      "policy": "judge_only",
      "source_used": "judge",
      "judge_score": 8.5,
      "deterministic_score": 10.0,
      "final_score": 8.5
    },
    "process": {
      "policy": "weighted",
      "source_used": "weighted",
      "judge_score": 9.0,
      "deterministic_score": 10.0,
      "final_score": 9.1
    }
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

## Dimension policies

Each dimension can be configured independently in the evaluation profile:

```yaml
final_aggregation:
  default_policy: judge_only      # applied to all dimensions not listed below
  dimensions:
    process:
      policy: weighted
      judge_weight: 0.9
      deterministic_weight: 0.1
```

### `judge_only` (default)

The final dimension score is the judge's score for that dimension. The deterministic result is recorded for reference but does not affect the score.

### `deterministic_only`

The final dimension score is derived from the deterministic checks mapped to that dimension. The judge score is ignored.

Deterministic checks produce a 0 or 10 per check. If multiple checks are mapped to the same dimension, the score is the proportion of passed checks, scaled to 0–10.

### `weighted`

```
final = (judge_score × judge_weight) + (deterministic_score × deterministic_weight)
```

Weights do not need to sum to 1.0; they are normalised internally. Useful when you want deterministic evidence to nudge the judge without overriding it.

---

## Hard expectation failure

If a deterministic check that maps to `task` fails, the aggregator treats it as a signal that the task was not completed. Depending on the dimension policy, this can:

- reduce the `process` or `task` dimension score if `weighted` or `deterministic_only` is configured
- appear as a warning in the final result for `judge_only` dimensions

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

## Inspecting the resolution

The `dimension_resolutions` field in the final result records, for every dimension:

- which policy was applied
- what source was used (`judge`, `deterministic`, `weighted`, or `missing`)
- the raw judge and deterministic scores before combination
- the final score after combination

This makes the aggregation fully auditable — you can always see exactly how each dimension score was derived.

---

## Cost-quality tradeoff

Every `FinalEvaluationResult` is associated with a `UsageSummary` that records:

- `run_cost_usd` — cost of the subject run (model tokens)
- `evaluation_cost_usd` — cost of the judge calls
- `total_cost_usd` — sum of both

Use `pae report --output json` to get the structured breakdown, or look at the `TOTAL_COST` column in the terminal output. The optional score/cost PNG chart plots this relationship visually for all models in the campaign.

→ [Reporting](reporting.md)
