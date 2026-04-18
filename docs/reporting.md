# Reporting

`personal_agent_eval` reporting consumes structured workflow results and renders:

- a per-model per-case CLI table
- a per-model summary table
- a JSON-serializable structured report
- basic ASCII charts for terminal use

The reporting layer does not re-read storage to reconstruct orchestration logic when a
workflow result already contains the relevant information.

## Input Shape

V1 reporting expects a workflow result shaped around `model_id` and `case_id`.

Example:

```json
{
  "command": "run-eval",
  "workspace_root": "/tmp/workspace",
  "suite_id": "benchmark_suite",
  "run_profile_id": "default_run",
  "evaluation_profile_id": "default_eval",
  "results": [
    {
      "model_id": "minimax/minimax-m2.7",
      "case_id": "case_alpha",
      "run_action": "reused",
      "evaluation_action": "executed",
      "run_status": "success",
      "evaluation_status": "success",
      "run_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "evaluation_fingerprint": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "final_score": 7.4,
      "warnings": ["Judge iteration 2 failed and was excluded."]
    }
  ]
}
```

## CLI Table

The first terminal-oriented output is a table at `model x case` granularity.

Example:

```text
MODEL                CASE        RUN      EVAL      SCORE  IN_TOK  OUT_TOK  COST_USD  WARNINGS
-------------------  ----------  -------  --------  -----  ------  -------  --------  --------
minimax/minimax-m2.7 case_alpha  reused   executed  7.40   120     40       0.005000  1
openai/gpt-5.4       case_alpha  executed reused    8.20   220     80       0.007500  0
```

`IN_TOK`, `OUT_TOK`, and `COST_USD` are workflow totals for that `model x case` row. When the
workflow includes judge calls, reporting sums the run usage and the judge usage together. When
`run_repetitions > 1`, reporting also sums usage and cost across repetitions while still averaging
scores.

## Per-Model Summary

Reporting also derives one summary row per model.

Example:

```text
MODEL                CASES  AVG_SCORE  RUNS_REUSED  RUNS_EXECUTED  EVALS_REUSED  EVALS_EXECUTED  IN_TOK  OUT_TOK  COST_USD  WARNINGS
-------------------  -----  ---------  -----------  -------------  -------------  --------------  ------  -------  --------  --------
minimax/minimax-m2.7 2      7.00       1            1              0              2               280     90       0.008000  1
openai/gpt-5.4       1      8.20       0            1              1              0               220     80       0.007500  0
```

## ASCII Charts

The V1 chart output is intentionally simple and terminal-friendly.

### Per-model dimension bars

```text
Model: minimax/minimax-m2.7
task         ###############----- 7.50
process      ##############------ 7.00
autonomy     #############------- 6.75
```

### Final-score comparison

```text
Model Comparison
openai/gpt-5.4       ################---- 8.20
minimax/minimax-m2.7 ##############------ 7.00
```

## Structured Report Output

The report is also available as a JSON-serializable structured object so that a later CLI
or web layer can reuse it directly.

Example:

```json
{
  "suite_id": "benchmark_suite",
  "case_results": [
    {
      "model_id": "minimax/minimax-m2.7",
      "case_id": "case_alpha",
      "run_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "evaluation_fingerprint": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "final_score": 7.4,
      "usage": {
        "input_tokens": 120,
        "output_tokens": 40,
        "total_tokens": 160,
        "reasoning_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.005
      }
    }
  ],
  "model_summaries": [
    {
      "model_id": "minimax/minimax-m2.7",
      "case_count": 2,
      "average_final_score": 7.0,
      "total_usage": {
        "input_tokens": 280,
        "output_tokens": 90,
        "total_tokens": 370,
        "reasoning_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.008
      }
    }
  ]
}
```
