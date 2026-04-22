---
name: personal-agent-eval
description: Use this skill whenever working with the personal_agent_eval (pae) benchmark framework in this repository. Covers everything needed to operate the library: running benchmarks with `pae run-eval`, creating and modifying test cases, suites, run profiles, and evaluation profiles, understanding fingerprints and incremental reuse, reading and interpreting evaluation outputs, configuring the LLM judge, and all `pae` CLI commands and flags. Trigger on any of these: "run a benchmark", "create a test case", "add a model to a suite", "configure the judge", "why is it reusing results", "how does scoring work", "how do I re-run a case", "what is a fingerprint", "set up a campaign", "add a deterministic check", "what does each dimension measure", "how does the openclaw runner work", or any question about how this library works.
---

# personal_agent_eval

`personal_agent_eval` (CLI: `pae`) is an open benchmark framework for LLM and agent-based systems. It takes a set of **test cases**, a **model or agent**, and a **judge configuration**, and produces a structured, reproducible score where deterministic checks serve as evidence for an LLM judge.

Every result is identified by a **SHA-256 fingerprint** of all inputs. Re-running the same configuration reuses stored results — no tokens spent twice. Adding a new case or model only runs what is missing.

---

## Two runner modes

| Mode | What it evaluates | How it runs |
|---|---|---|
| `llm_probe` | A raw LLM with optional tool use | Direct HTTP call to OpenRouter |
| `openclaw` | A full autonomous agent | `docker run` with a pinned container image |

Both modes share the same config schema, evaluation pipeline, and output format.

---

## The 5 config files

| Config type | Path | Answers |
|---|---|---|
| Test case | `configs/cases/<case_id>/test.yaml` | What to test |
| Suite | `configs/suites/<suite_id>.yaml` | Which cases and which models |
| Run profile | `configs/run_profiles/<id>.yaml` | How to execute (temperature, tokens, retries…) |
| Evaluation profile | `configs/evaluation_profiles/<id>.yaml` | How to judge and aggregate repeated judge runs |
| OpenClaw agent | `configs/agents/<id>/agent.yaml` + `workspace/` | Reusable agent definition (openclaw only) |

---

## Quick start

```bash
# install
uv sync --group dev
export OPENROUTER_API_KEY=sk-or-v1-...

# run the shipped llm_probe example (no Docker needed)
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini

# run the OpenClaw example (requires Docker)
uv run pae run-eval \
  --suite openclaw_examples \
  --run-profile openclaw_examples \
  --evaluation-profile judge_gpt54_mini
```

Run either command a second time — the `RUN` and `EVAL` columns show `reuse`. No tokens spent.

---

## Creating a campaign from scratch

1. **Write a test case** — `configs/cases/<case_id>/test.yaml`
2. **Create or update a suite** — `configs/suites/<suite_id>.yaml` (list your case IDs and models)
3. **Create or reuse a run profile** — `configs/run_profiles/<id>.yaml` (temperature, retries, etc.)
4. **Create or reuse an evaluation profile** — `configs/evaluation_profiles/<id>.yaml` (judge model, aggregation)
5. **Run** — `uv run pae run-eval --suite <id> --run-profile <id> --evaluation-profile <id>`
6. **Read results** — open `outputs/evaluations/.../evaluation_result_summary_1.md`

---

## Config authoring — minimal examples

### `test.yaml` — llm_probe

```yaml
schema_version: 1
case_id: my_tool_case
title: My tool case
runner:
  type: llm_probe
input:
  messages:
    - role: user
      content: |
        Use real tools and follow these steps exactly:
        1. Run `printf 'hello-world\n'` with `exec_shell`.
        2. Write `/tmp/hello.txt` with that content using `write_file`.
        3. Read the file using `read_file`.
        4. Reply in 2–4 lines confirming what you did.
  context:
    llm_probe:
      tools: [exec_shell, write_file, read_file]
expectations:
  hard_expectations:
    - text: Uses tools to obtain the content instead of inventing it.
    - text: Creates /tmp/hello.txt and confirms the saved text.
  soft_expectations:
    - text: Response is brief and clearly confirms the final file content.
rubric:
  version: 1
  scale:
    min: 0
    max: 10
    anchors:
      "10": Executes all required tool steps; file contains the exact marker; answer confirms content briefly.
      "7": Mostly correct with minor clarity issues.
      "4": Partial completion; missing a required step or confirmation.
      "0": No attempt / irrelevant / empty output.
  criteria:
    - name: Tool-grounded correctness
      what_good_looks_like: Uses exec_shell/write_file/read_file and reports the observed file contents.
      what_bad_looks_like: Invents results or skips required tool steps.
    - name: Concise confirmation
      what_good_looks_like: Confirms actions and final content in 2–4 lines.
      what_bad_looks_like: Overly verbose or unclear confirmation.
  scoring_instructions: >
    Use this rubric to set overall.score. If a hard expectation or
    deterministic check fails, cap overall.score (typically <= 4).
deterministic_checks:
  - check_id: response-present
    dimensions: [task]
    declarative:
      kind: final_response_present
  - check_id: file-written
    dimensions: [process]
    declarative:
      kind: file_contains
      path: /tmp/hello.txt
      text: hello-world
tags: [smoke]
```

Available tools for `llm_probe`: `exec_shell`, `write_file`, `read_file`, `web_search`.

Both `expectations` and `rubric` are shown to the judge. `expectations` state what must happen; the `rubric` gives the judge a calibrated scoring scale and explicit criteria. All shipped cases include both.

### `test.yaml` — openclaw

```yaml
schema_version: 1
case_id: my_openclaw_case
title: My OpenClaw case
runner:
  type: openclaw
input:
  messages:
    - role: user
      content: |
        Create a file `report.md` in the workspace.
        The file must contain a title `# Report` and the literal line `hello-world`.
        Briefly confirm creation when done.
  context:
    openclaw:
      expected_artifact: report.md
expectations:
  hard_expectations:
    - text: Produces report.md in the workspace.
    - text: Includes the literal marker hello-world in report.md.
  soft_expectations:
    - text: Final response briefly confirms the artifact creation.
rubric:
  version: 1
  scale:
    min: 0
    max: 10
    anchors:
      "10": report.md exists with required content and marker; response briefly confirms creation.
      "7": Mostly complete; minor formatting or clarity issues.
      "4": Missing required content or unclear confirmation.
      "0": No attempt / irrelevant / empty output.
  criteria:
    - name: Required artifact content
      what_good_looks_like: report.md contains the title and the literal marker line.
      what_bad_looks_like: report.md missing or missing required lines.
    - name: Brief confirmation
      what_good_looks_like: Final response confirms creation briefly.
      what_bad_looks_like: No confirmation or overly verbose response.
  scoring_instructions: >
    Use this rubric to set overall.score. If a hard expectation or
    deterministic check fails, cap overall.score (typically <= 4).
deterministic_checks:
  - check_id: response-present
    dimensions: [task]
    declarative:
      kind: final_response_present
  - check_id: report-file
    dimensions: [process]
    declarative:
      kind: openclaw_workspace_file_present
      relative_path: report.md
      contains: hello-world
tags: [smoke]
```

`expectations` and `rubric` are optional — the judge can evaluate a run without them. They are recommended because they give the judge explicit context about what success looks like, which produces more consistent and reliable scores. `deterministic_checks` are also optional and independent of both.

### `suite.yaml`

```yaml
schema_version: 1
suite_id: my_suite
title: My benchmark suite
models:
  - model_id: gpt4o_mini
    requested_model: openai/gpt-4o-mini
    label: GPT-4o mini
  - model_id: minimax_m27
    requested_model: minimax/minimax-m2.7
case_selection:
  include_case_ids: [my_tool_case]
  # alternatives:
  # include_tags: [smoke]
  # exclude_tags: [slow]
```

### `run_profile.yaml`

```yaml
schema_version: 1
run_profile_id: my_run
title: My run profile
runner_defaults:
  temperature: 0
  max_tokens: 1024
  timeout_seconds: 60
  max_turns: 8
  retries: 2
execution_policy:
  max_concurrency: 1
  run_repetitions: 1
  fail_fast: false
  stop_on_runner_error: true
# openclaw only — add this block for openclaw runs:
# openclaw:
#   agent_id: support_agent
#   image: ghcr.io/openclaw/openclaw:2026.4.15
#   timeout_seconds: 300
```

### `evaluation_profile.yaml`

```yaml
schema_version: 1
evaluation_profile_id: my_eval
title: My eval profile
judge_system_prompt_path: prompts/judge_system_default.md
judges:
  - judge_id: my_judge
    type: llm_probe
    model: openai/gpt-5.4-mini
judge_runs:
  - judge_run_id: single_run
    judge_id: my_judge
    repetitions: 1
aggregation:
  method: median
security_policy:
  allow_local_python_hooks: false
  redact_secrets: true
```

The shipped profile `configs/evaluation_profiles/judge_gpt54_mini.yaml` uses `openai/gpt-5.4-mini` and is ready to use.

---

## Scoring dimensions

The judge scores six dimensions on a **0–10 scale**. See `skill/references/evaluation.md` for detailed descriptions, how deterministic signals are surfaced, and how to debug scores.

| Dimension | What it measures |
|---|---|
| `task` | Output fulfills the stated goal (correct content, files, format) |
| `process` | Sound approach: right tools used, constraints respected, no hallucinations |
| `autonomy` | Independent operation — sensible decisions, no over-asking |
| `closeness` | Matches a good human response in tone, framing, and completeness |
| `efficiency` | Achieves the goal with reasonable resource use (no unnecessary calls or noise) |
| `spark` | Something noteworthy — useful insight, elegant shortcut, thoughtful initiative |

**`final_score`** is the judge's holistic overall assessment (0–10). It is **not** a weighted average of the six dimensions — it is the judge's single top-level verdict. Dimensions are for diagnostics.

---

## CLI reference

```bash
uv run pae --help
uv run pae <command> --help
```

### Global flags

| Flag | Description |
|---|---|
| `--log-level` | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, `CRITICAL` |
| `--version` | Print package version |

### Commands

| Command | What it does |
|---|---|
| `pae run` | Execute runs only; skip evaluation |
| `pae eval` | Run missing runs + evaluate; reuse existing run and eval artifacts |
| `pae run-eval` | Alias for `pae eval` |
| `pae report` | Render report from stored artifacts (no API calls) |

### Common flags (`eval` / `run-eval` / `report`)

| Flag | Description |
|---|---|
| `--suite <id or path>` | Suite ID or explicit YAML path |
| `--run-profile <id or path>` | Run profile ID or explicit YAML path |
| `--evaluation-profile <id or path>` | Evaluation profile ID or explicit YAML path |
| `--output json` | Machine-readable JSON on stdout |
| `--no-chart` | Skip writing the score/cost PNG |
| `--chart PATH` | Write the chart to a custom path |
| `--chart-footnote TEXT` | Add a caption to the chart |

ID resolution: `--suite my_suite` resolves to `configs/suites/my_suite.yaml` automatically.

---

## Fingerprints and reuse

Before executing any `(model, case, repetition)`, the framework computes a SHA-256 of all execution inputs: model, messages, config parameters, tool list, and workspace content (for OpenClaw). If a matching artifact exists in `outputs/`, it is reused — no tokens spent.

**What changes the run fingerprint** (triggers re-run): temperature, max_tokens, max_turns, retries, seed, model ID, case input messages, attachment content, OpenClaw workspace files.

**What does NOT change the run fingerprint**: adding a new case to the suite, changing the suite title, increasing `run_repetitions` (new repetitions run; existing ones reuse).

**Evaluation fingerprint is separate** — changing the judge model, judge aggregation, prompt, anchors, or security policy re-evaluates without re-running the model.

**To force a re-run:**

```bash
# option 1: delete the stored artifact
rm outputs/runs/suit_<suite_id>/run_profile_<fp6>/<model_id>/<case_id>/run_1.json
rm outputs/runs/suit_<suite_id>/run_profile_<fp6>/<model_id>/<case_id>/run_1.fingerprint_input.json

# option 2: change any execution parameter in run_profile.yaml
# new fingerprint → new directory → all cases re-run; old results preserved

# option 3: create a narrow suite
# case_selection:
#   include_case_ids: [only_this_case]
```

---

## Reading outputs

```
outputs/
├── charts/<eval_profile_id>/score_cost.png
├── runs/suit_<suite_id>/run_profile_<fp6>/
│   └── <model_id>/<case_id>/
│       ├── run_1.json                           ← raw trace, token usage, provider metadata
│       └── run_1.fingerprint_input.json         ← exact payload that was hashed
└── evaluations/suit_<suite_id>/
    └── evaluation_profile_<fp6>/eval_profile_<eval_id>_<fp6>/
        └── <model_id>/<case_id>/
            ├── evaluation_result_summary_1.md   ← START HERE: verdict + evidence
            ├── judge_1.prompt.debug.md          ← exact prompt the judge saw
            └── raw_outputs/
                ├── final_result_1.json          ← judge score + deterministic summaries
                ├── judge_1.json                 ← raw aggregated judge response
                └── judge_1.prompt.user.json     ← structured subject view payload
```

**Reading order:**
1. `evaluation_result_summary_1.md` — final score, judge evidence, dimension breakdown
2. `judge_1.prompt.debug.md` — what the judge actually saw (check here if a score seems wrong)
3. `raw_outputs/final_result_1.json` — judge scores, deterministic summaries, and final reported dimensions
4. `run_1.json` — full event trace (tool calls, messages, token usage) for runner-level debug

---

## Common recipes

### Add a new model

Add to `models:` in the suite YAML and re-run. Only the new model's cases execute.

### Add a new test case

Create `configs/cases/<new_case_id>/test.yaml`, add the ID to `case_selection.include_case_ids`, re-run.

### Change the judge without re-running

Edit `model:` in the evaluation profile. Evaluation fingerprint changes → new `eval_profile_<id>_<fp6>` directory → evaluations re-run, run artifacts reused.

### Increase judge reliability

```yaml
judge_runs:
  - judge_run_id: triple_run
    judge_id: my_judge
    repetitions: 3
aggregation:
  method: median
```

### Run only specific cases

```yaml
case_selection:
  include_case_ids: [case_a, case_b]
```

---

## Repository layout

```
configs/
  cases/<case_id>/test.yaml
  suites/<suite_id>.yaml
  run_profiles/<id>.yaml
  evaluation_profiles/<id>.yaml
  agents/<agent_id>/agent.yaml + workspace/
src/personal_agent_eval/          ← Python source (runners, judge, aggregator, CLI)
tests/                            ← pytest suite, all mocked
docs/                             ← MkDocs documentation source
outputs/                          ← generated at runtime; not committed
```

---

## Deeper reference

- `skill/references/config-fields.md` — full field-by-field YAML reference for all config types
- `skill/references/evaluation.md` — scoring dimensions in depth, what the judge sees, and how to read and debug evaluation artifacts
- `uv run mkdocs serve` — browse the full documentation site locally
