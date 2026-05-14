# Reporting

The reporting layer consumes structured workflow results and renders them in three forms: **terminal tables**, **structured JSON**, and an optional **score/cost PNG chart**.

---

## Terminal output

The default `--output text` mode renders two tables and a cost summary.

### Header

```
Suite:             llm_probe_examples
Run profile:       llm_probe_examples
Evaluation:        judge_gpt54_mini
Run cost:          $0.0003
Evaluation cost:   $0.0018
Total cost:        $0.0021
```

### Per-case table

Each row is one `(model, case)` combination:

```
MODEL          CASE                          RUN   EVAL  SCORE  LATENCY_S  IN_TOK  OUT_TOK  RUN_COST  EVAL_COST  TOTAL_COST  WARNINGS
─────────────  ────────────────────────────  ────  ────  ─────  ─────────  ──────  ───────  ────────  ─────────  ──────────  ────────
minimax_m27    llm_probe_tool_example        exec  exec   8.50      12.3     580      120    $0.0001   $0.0009    $0.0010        0
minimax_m27    llm_probe_browser_example     reuse exec   7.00       9.1     490       95    $0.0002   $0.0009    $0.0011        0
```

Column reference:

| Column | Description |
|---|---|
| `MODEL` | Model ID from the suite |
| `CASE` | Case ID |
| `RUN` | `exec` = newly run; `reuse` = loaded from storage |
| `EVAL` | `exec` = newly evaluated; `reuse` = loaded from storage |
| `SCORE` | Final score (0–10) |
| `LATENCY_S` | Wall-clock duration of the subject run in seconds |
| `IN_TOK` | Input tokens |
| `OUT_TOK` | Output tokens |
| `RUN_COST` | USD cost of the subject run |
| `EVAL_COST` | USD cost of the judge evaluation |
| `TOTAL_COST` | `RUN_COST + EVAL_COST` |
| `WARNINGS` | Number of non-fatal warnings (e.g. failed judge iterations) |

### Per-model summary

```
SUMMARY
Model          Cases  Avg Score  Avg Latency  In Tok  Out Tok  Run Cost  Eval Cost  Total Cost  Warnings
─────────────  ─────  ─────────  ───────────  ──────  ───────  ────────  ─────────  ──────────  ────────
minimax_m27    2       7.75       10.7s        1070     215    $0.0003   $0.0018    $0.0021        0
```

### ASCII dimension bars

After the summary, the CLI renders a quick visual of per-dimension scores for each model:

```
Model: minimax_m27
task         ████████████████░░░░ 8.50
process      █████████████████░░░ 9.00
autonomy     ████████████████░░░░ 8.00
closeness    █████████████████░░░ 8.50
efficiency   ███████████████░░░░░ 7.50
spark        ████████████░░░░░░░░ 6.00

Model comparison
minimax_m27    ████████████████░░░░ 8.50
```

---

## JSON output

Use `--output json` to get a machine-readable structured report on stdout:

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini \
  --output json
```

The JSON report contains:

```json
{
  "command": "run-eval",
  "suite_id": "llm_probe_examples",
  "run_profile_id": "llm_probe_examples",
  "evaluation_profile_id": "judge_gpt54_mini",
  "workspace_root": "/path/to/repo",
  "run_cost_usd": 0.0003,
  "evaluation_cost_usd": 0.0018,
  "total_cost_usd": 0.0021,
  "case_results": [
    {
      "model_id": "minimax_m27",
      "case_id": "llm_probe_tool_example",
      "run_action": "executed",
      "evaluation_action": "executed",
      "run_status": "success",
      "evaluation_status": "success",
      "run_fingerprint": "a3f8c2...",
      "evaluation_fingerprint": "d7e1b3...",
      "final_score": 8.5,
      "run_latency_seconds": 12.3,
      "run_usage": { "cost_usd": 0.0001 },
      "evaluation_usage": { "cost_usd": 0.0009 },
      "usage": {
        "input_tokens": 580,
        "output_tokens": 120,
        "total_tokens": 700,
        "cost_usd": 0.0010
      },
      "warnings": []
    }
  ],
  "model_summaries": [
    {
      "model_id": "minimax_m27",
      "case_count": 2,
      "average_final_score": 7.75,
      "average_latency_seconds": 10.7,
      "run_cost_usd": 0.0003,
      "evaluation_cost_usd": 0.0018,
      "total_usage": {
        "input_tokens": 1070,
        "output_tokens": 215,
        "cost_usd": 0.0021
      }
    }
  ]
}
```

Chart status messages are always written to **stderr** so the JSON on stdout stays valid and pipeable.

### Floating-point precision

JSON fields use consistent rounding for readability:

- scores and dimension values: 5 decimal places
- USD costs: 6 decimal places
- durations and latency: 4 decimal places

Fingerprint input payloads are **never rounded** — the hash must remain stable.

---

## Score/cost chart (PNG)

For `pae eval`, `pae run-eval`, and `pae report`, the CLI writes a PNG bubble chart by default:

- **Default path:** `outputs/charts/<evaluation_profile_id>/score_cost.png`
- X axis: total cost per model (USD)
- Y axis: mean final score per model
- Bubble area: proportional to mean run latency
- Labels are offset from the bubbles to avoid hiding points. The renderer also has small per-model overrides for known crowded labels in the OpenClaw benchmark.

```bash
# use the default path
uv run pae run-eval ...

# write to a custom path
uv run pae run-eval ... --chart /tmp/results.png

# add a caption
uv run pae run-eval ... --chart-footnote "Run date: 2026-04-22, model: minimax-m2.7"

# skip the chart
uv run pae run-eval ... --no-chart
```

The chart requires the optional `[charts]` extra:

```bash
uv sync --extra charts
# or: pip install 'personal-agent-eval[charts]'
```

If `matplotlib` is not installed, the CLI logs a warning and continues with exit code 0.

---

## Storage hints in case results

Each row in `case_results` may include storage hints when a run artifact exists:

| Field | Description |
|---|---|
| `stored_run_artifact_path` | Workspace-relative path to the `run_N.json` file |
| `stored_run_fingerprint_input_path` | Workspace-relative path to the fingerprint input JSON |
| `stored_run_artifacts_dir` | Workspace-relative path to the `run_N.artifacts/` directory |
| `openclaw_evidence` | For OpenClaw runs: `agent_id`, `container_image`, and a map of artifact type → workspace-relative path |

These fields are omitted on rows without a run artifact and on aggregated multi-repetition rows.

---

## Regenerating a report

To re-render the terminal output or chart from stored artifacts without re-running anything:

```bash
uv run pae report \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

This reads only from `outputs/` — no API calls are made.
