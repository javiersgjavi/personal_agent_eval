# CLI Reference

`personal_agent_eval` exposes a single entrypoint called `pae`. Inside a repository checkout, run it via `uv`:

```bash
uv run pae --help
```

If you have installed the package into an active virtualenv, you can also run `pae` directly.

---

## Global flags

| Flag | Default | Description |
|---|---|---|
| `--version` | — | Print the package version and exit |
| `--log-level` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

---

## Commands

### `pae run`

Executes the runs defined by a suite and run profile. Skips any `(model, case, repetition)` combination that already has a matching stored fingerprint.

```bash
uv run pae run \
  --suite <id-or-path> \
  --run-profile <id-or-path>
```

**When to use it:** When you want to collect raw run artifacts without spending tokens on evaluation. Useful when you plan to evaluate later with multiple judge profiles, or when you want to inspect `run_1.json` before committing to a full evaluation.

**What it writes:** `RunArtifact` JSON files under `outputs/runs/`.

**Flags:**

| Flag | Required | Description |
|---|---|---|
| `--suite` | yes | Suite ID or explicit YAML path |
| `--run-profile` | yes | Run profile ID or explicit YAML path |
| `--output` | no | `text` (default) or `json` |

---

### `pae eval`

Runs any missing runs **and** evaluates all results. If a run already exists, it is reused; if an evaluation already exists for that run + evaluation profile, it is also reused.

```bash
uv run pae eval \
  --suite <id-or-path> \
  --run-profile <id-or-path> \
  --evaluation-profile <id-or-path>
```

**When to use it:** The standard command for an evaluation campaign. Handles both missing runs and missing evaluations in one shot.

**What it writes:** `RunArtifact` JSON files under `outputs/runs/`, evaluation results under `outputs/evaluations/`, and optionally a chart PNG under `outputs/charts/`.

**Flags:**

| Flag | Required | Description |
|---|---|---|
| `--suite` | yes | Suite ID or explicit YAML path |
| `--run-profile` | yes | Run profile ID or explicit YAML path |
| `--evaluation-profile` | yes | Evaluation profile ID or explicit YAML path |
| `--output` | no | `text` (default) or `json` |
| `--no-chart` | no | Skip writing the score/cost PNG chart |
| `--chart PATH` | no | Write the chart to a custom path |
| `--chart-footnote TEXT` | no | Optional caption at the bottom of the chart |

---

### `pae run-eval`

Identical to `pae eval`. Both commands run missing runs first and then evaluate. The name is kept as an alias for clarity in scripts.

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

---

### `pae report`

Reads **already stored artifacts** and renders the report without executing anything. No tokens are spent. Useful for regenerating a report or chart after tweaking the evaluation profile configuration (if you already have stored evaluations matching the new fingerprint).

```bash
uv run pae report \
  --suite <id-or-path> \
  --run-profile <id-or-path> \
  --evaluation-profile <id-or-path>
```

**When to use it:** When results are already stored and you just want to see the terminal output or regenerate the chart.

**Same flags as `pae eval`.**

---

## Config ID resolution

All `--suite`, `--run-profile`, and `--evaluation-profile` flags accept **either** a config ID **or** an explicit path:

```bash
# using IDs (auto-resolved from conventional directories)
pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini

# using explicit paths
pae run-eval \
  --suite configs/suites/llm_probe_examples.yaml \
  --run-profile configs/run_profiles/llm_probe_examples.yaml \
  --evaluation-profile configs/evaluation_profiles/judge_gpt54_mini.yaml
```

An ID is resolved by looking for `<id>.yaml` or `<id>.yml` under the conventional directory:

| Flag | Conventional directory |
|---|---|
| `--suite` | `configs/suites/` |
| `--run-profile` | `configs/run_profiles/` |
| `--evaluation-profile` | `configs/evaluation_profiles/` |

The workspace root is derived from the location of the `--suite` file: the CLI walks up from `configs/suites/` to find the parent directory that contains `configs/`.

---

## Output formats

### Terminal (default)

The default `--output text` mode renders human-readable tables:

```
Suite:             llm_probe_examples
Run profile:       llm_probe_examples
Evaluation:        judge_gpt54_mini
Run cost:          $0.0003
Evaluation cost:   $0.0018
Total cost:        $0.0021

MODEL          CASE                        RUN   EVAL  SCORE  LATENCY_S  RUN_COST  EVAL_COST  TOTAL_COST
─────────────  ──────────────────────────  ────  ────  ─────  ─────────  ────────  ─────────  ──────────
minimax_m27    llm_probe_tool_example      exec  exec   8.50      12.3    $0.0001   $0.0009    $0.0010
minimax_m27    llm_probe_browser_example   exec  exec   7.00       9.1    $0.0002   $0.0009    $0.0011

SUMMARY
Model          Cases  Avg Score  Avg Latency  Run Cost  Eval Cost  Total Cost
─────────────  ─────  ─────────  ───────────  ────────  ─────────  ──────────
minimax_m27    2       7.75      10.7s        $0.0003   $0.0018    $0.0021
```

The `RUN` and `EVAL` columns show either `exec` (newly computed) or `reuse` (loaded from storage).

### JSON

Use `--output json` to get a machine-readable structured report on stdout:

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini \
  --output json
```

Chart status messages go to **stderr**, so the JSON on stdout stays valid and pipeable.

---

## The score/cost chart

For `pae eval`, `pae run-eval`, and `pae report`, the CLI writes a PNG chart by default:

- **Default path:** `outputs/charts/<evaluation_profile_id>/score_cost.png`
- Each bubble is one model; X axis = total cost, Y axis = mean score, bubble size = mean latency
- Requires the optional `[charts]` extra: `uv sync --extra charts`

```bash
# custom chart path
uv run pae run-eval ... --chart /tmp/results.png

# add a caption
uv run pae run-eval ... --chart-footnote "Run date: 2026-04-22"

# skip the chart entirely
uv run pae run-eval ... --no-chart
```

---

## Re-running specific cases

The framework reuses stored results by fingerprint. To force a re-run of specific cases, you have two options:

### Option 1: Delete the stored run artifact

```bash
# force re-run of one specific case for one model
rm outputs/runs/suit_<suite_id>/run_profile_<fp6>/<model_id>/<case_id>/run_1.json
rm outputs/runs/suit_<suite_id>/run_profile_<fp6>/<model_id>/<case_id>/run_1.fingerprint_input.json

# then re-run the campaign
uv run pae run-eval ...
```

The workflow detects the missing artifact and re-executes only that case.

### Option 2: Create a narrow suite

Create a temporary suite with `case_selection.include_case_ids` limited to the cases you want to re-run:

```yaml
# configs/suites/rerun_tool_case.yaml
schema_version: 1
suite_id: rerun_tool_case
title: "Targeted re-run"
models:
  - model_id: minimax_m27
    requested_model: minimax/minimax-m2.7
case_selection:
  include_case_ids:
    - llm_probe_tool_example
```

```bash
uv run pae run-eval \
  --suite rerun_tool_case \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

This creates a separate campaign directory under `outputs/runs/suit_rerun_tool_case/` — the original campaign is untouched.

### Option 3: Change the run profile

Any change to a run profile field that affects execution (e.g. `temperature`, `max_tokens`) creates a new fingerprint and a new campaign directory. All cases are re-run, and the previous results are preserved under the old directory.

→ [Fingerprints & reuse](fingerprints.md) — full explanation

---

## Environment variables

| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | Required for all LLM calls (runs and judge) |
| `PERSONAL_AGENT_EVAL_RUN_OPENROUTER_E2E=1` | Opt-in to the real OpenRouter smoke test |
| `PERSONAL_AGENT_EVAL_OPENROUTER_E2E_RUN_MODEL` | Override run model in the e2e test |
| `PERSONAL_AGENT_EVAL_OPENROUTER_E2E_JUDGE_MODEL` | Override judge model in the e2e test |
| `PERSONAL_AGENT_EVAL_OPENCLAW_DOCKER_FULL_ENV=1` | Forward the full host env to OpenClaw containers |

The `.env` file at the repository root is loaded automatically by the CLI.

---

## Checking version

```bash
uv run pae --version
```
