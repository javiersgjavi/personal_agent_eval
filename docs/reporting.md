# Reporting

`personal_agent_eval` reporting consumes structured workflow results and renders:

- a per-model per-case CLI table
- a per-model summary table
- a JSON-serializable structured report
- basic ASCII charts for terminal use
- optional **score vs cost** bubble chart (PNG) for `eval`, `run-eval`, and `report`

The reporting layer does not re-read storage to reconstruct orchestration logic when a
workflow result already contains the relevant information.

## Input Shape

V1 reporting expects a workflow result shaped around `model_id` and `case_id`. Each case row may
include:

- `run_usage` / `evaluation_usage`: token and cost for the subject run vs judge calls
- `usage`: combined total for that row
- `run_latency_seconds`: wall-clock duration of the subject run (from the run artifact `timing`)
- **Storage hints** (when a run artifact exists for that row): `runner_type`,
  `stored_run_artifact_path`, `stored_run_fingerprint_input_path`, and `stored_run_artifacts_dir`
  as paths **relative to the workspace root** (the same root that contains `outputs/`).
- **OpenClaw**: optional `openclaw_evidence` with `agent_id`, `container_image`, and
  `evidence_paths` (maps each stable `artifact_type` to a workspace-relative file path). These
  fields are omitted on rows without a run (for example missing artifacts) and omitted for
  aggregated multi-repetition rows where per-repetition paths do not apply.

Example (abbreviated):

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
      "run_latency_seconds": 12.5,
      "run_usage": { "cost_usd": 0.002 },
      "evaluation_usage": { "cost_usd": 0.003 },
      "usage": { "input_tokens": 120, "output_tokens": 40, "cost_usd": 0.005 },
      "warnings": ["Judge iteration 2 failed and was excluded."]
    }
  ],
  "summary": {
    "run_cost_usd": 0.01,
    "evaluation_cost_usd": 0.02,
    "total_cost_usd": 0.03
  }
}
```

## CLI header and tables

The human-readable report starts with suite metadata and **aggregate costs (USD)**:

- runs (subject model only)
- evaluation (judges)
- total

### Per-case table

Columns include score, **latency** (`LATENCY_S`), tokens, **cost split** (`RUN_COST`, `EVAL_COST`,
`TOTAL_COST`), and warning count. `TOTAL_COST` matches `run_usage + evaluation_usage` for that row.

Example (illustrative):

```text
MODEL  CASE  RUN  EVAL  SCORE  LATENCY_S  IN_TOK  OUT_TOK  RUN_COST  EVAL_COST  TOTAL_COST  WARNINGS
-----  ----  ---  ----  -----  ---------  ------  -------  --------  ---------  ----------  --------
...
```

### Per-model summary

Includes **average latency** (`AVG_LATENCY_S`) and the same cost columns aggregated per model.

Example (illustrative):

```text
MODEL  CASES  AVG_SCORE  ...  AVG_LATENCY_S  IN_TOK  OUT_TOK  RUN_COST  EVAL_COST  TOTAL_COST  WARNINGS
-----  -----  ---------  ...  -------------  ------  -------  --------  ---------  ----------  --------
...
```

When `run_repetitions > 1`, usage and cost sums include all repetitions; scores and dimensions
are aggregated per workflow rules; latency is averaged over rows that have `run_latency_seconds`.

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

## Score vs cost chart (PNG)

For **`pae eval`**, **`pae run-eval`**, and **`pae report`**, the CLI **writes a PNG by default**
(unless disabled):

- **Default path:** `{workspace_root}/outputs/charts/<evaluation_profile_id>/score_cost.png`
- **`--no-chart`:** skip writing the PNG
- **`--chart PATH`:** write to a custom path instead of the default
- **`--chart-footnote TEXT`:** optional caption at the bottom of the figure

The chart plots **mean score vs total cost per model**; **bubble area** reflects **mean run latency**
when available. Success and failure messages for the chart are printed to **stderr** so
`--output json` remains valid JSON on stdout.

Requires optional dependencies: install with `pip install 'personal-agent-eval[charts]'` or
`uv sync --extra charts` (includes `matplotlib`; `adjustText` improves label placement).

If `matplotlib` is missing or no model has an average score, the CLI logs a warning and continues
(exit code 0).

## Structured Report Output

Floating-point fields in JSON (CLI `--output json`, artifacts under `outputs/`, and programmatic
`to_json_dict()`) are **rounded for readability** while keeping enough precision for downstream
math: typically **5 decimals** for scores and dimension values, **6** for USD costs, **4** for
durations/latency. Fingerprint hash inputs (`RunFingerprintPayload`, `EvaluationFingerprintPayload`,
and stored fingerprint-input records) are **not** rounded so hashes stay stable.

The structured report object (`--output json` or `WorkflowReporter.build_report`) includes:

Top-level fields include:

- `run_cost_usd`, `evaluation_cost_usd`, `total_cost_usd` (workflow totals)
- `case_results`: each row includes `run_usage`, `evaluation_usage`, `usage`, and
  `run_latency_seconds` when present
- `model_summaries`: includes `run_cost_usd`, `evaluation_cost_usd`, `total_usage`, and
  `average_latency_seconds`

Example (abbreviated):

```json
{
  "suite_id": "benchmark_suite",
  "run_cost_usd": 0.006,
  "evaluation_cost_usd": 0.0095,
  "total_cost_usd": 0.0155,
  "case_results": [
    {
      "model_id": "minimax/minimax-m2.7",
      "case_id": "case_alpha",
      "run_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "evaluation_fingerprint": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "final_score": 7.4,
      "run_latency_seconds": 12.5,
      "run_usage": { "cost_usd": 0.002 },
      "evaluation_usage": { "cost_usd": 0.003 },
      "usage": {
        "input_tokens": 120,
        "output_tokens": 40,
        "total_tokens": 160,
        "cost_usd": 0.005
      }
    }
  ],
  "model_summaries": [
    {
      "model_id": "minimax/minimax-m2.7",
      "case_count": 2,
      "average_final_score": 7.0,
      "average_latency_seconds": 10.75,
      "run_cost_usd": 0.003,
      "evaluation_cost_usd": 0.005,
      "total_usage": {
        "input_tokens": 280,
        "output_tokens": 90,
        "cost_usd": 0.008
      }
    }
  ]
}
```
