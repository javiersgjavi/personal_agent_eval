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
| Test case | `configs/cases/<case_id>/test.yaml` or grouped as `configs/cases/<group>/<case_id>/test.yaml` | What to test |
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

1. **Write a test case** — `configs/cases/<case_id>/test.yaml` or grouped as `configs/cases/<group>/<case_id>/test.yaml`
2. **Create or update a suite** — `configs/suites/<suite_id>.yaml` (list your case IDs and models)
3. **Create or reuse a run profile** — `configs/run_profiles/<id>.yaml` (temperature, retries, etc.)
4. **Create or reuse an evaluation profile** — `configs/evaluation_profiles/<id>.yaml` (judge model, aggregation)
5. **Run** — `uv run pae run-eval --suite <id> --run-profile <id> --evaluation-profile <id>`
6. **Read results** — open `outputs/evaluations/.../evaluation_result_summary_1.md`

---

## Config authoring

Use the real examples in `configs/` as templates, and use the references for complete YAML shapes:

| Goal | Start from | Reference |
|---|---|---|
| Raw LLM/tool test | `configs/cases/llm_probe_tool_example/test.yaml` | `skill/references/config-fields.md` |
| OpenClaw single-turn test | `configs/cases/openclaw_tool_example/test.yaml` | `skill/references/config-fields.md` |
| OpenClaw multiturn test | `configs/cases/openclaw_multiturn_example/test.yaml` | `skill/references/openclaw-agents.md` |
| Suite/run/eval profiles | `configs/suites/*`, `configs/run_profiles/*`, `configs/evaluation_profiles/*` | `skill/references/config-fields.md` |

Authoring rules:

- `runner.type: llm_probe` sends messages directly to OpenRouter and can expose tools via `input.context.llm_probe.tools`.
- `runner.type: openclaw` runs an autonomous agent in Docker. Put expected workspace outputs under `input.context.openclaw.expected_artifact`.
- For OpenClaw suites, `run_profile.openclaw.agent_id` is the default agent. Use `suite.openclaw.agent_assignments` to route different cases or tags to different agents in the same suite.
- For OpenClaw follow-up messages, use `input.turns`. The harness invokes `openclaw agent` once per turn with the same workspace, state directory, and `--session-id`; `input.messages` is initial context for the first turn.
- For GPT-5.x reasoning, set `primary_params.reasoning.effort` on suite models for OpenClaw primaries, and `request_options.reasoning.effort` on judges. Typical values are `medium` for thinking and `none` for fast/no-reasoning judging.
- Include `expectations` and `rubric` whenever possible. They make judge output more stable and easier to debug.
- Add deterministic checks for hard evidence: `final_response_present`, file checks for `llm_probe`, and `openclaw_workspace_file_present` for OpenClaw workspace outputs.

Do not duplicate full YAML examples in this file. If a field is unclear, open `skill/references/config-fields.md`; if an OpenClaw workspace/agent detail is unclear, open `skill/references/openclaw-agents.md`.

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

Before executing any `(model, case, repetition)`, the framework computes a SHA-256 of all execution inputs: model, messages, turns, config parameters, tool list, and workspace content (for OpenClaw). If a matching artifact exists in `outputs/`, it is reused — no tokens spent.

**What changes the run fingerprint** (triggers re-run): temperature, max_tokens, max_turns, retries, seed, model ID, case input messages, case input turns, attachment content, OpenClaw workspace files.

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
│       ├── run_1.json                              ← raw trace, token usage, provider metadata
│       ├── run_1.fingerprint_input.json            ← exact payload that was hashed
│       └── run_1.artifacts/                        ← openclaw only
│           ├── openclaw_config--openclaw.json      ← generated container config
│           ├── openclaw_workspace_diff--*.diff     ← what the agent changed
│           ├── openclaw_key_output_1--<file>       ← extracted expected artifact
│           ├── openclaw_logs--openclaw.log         ← command log
│           ├── openclaw_raw_trace--*.json          ← container stdout/stderr; all turn payloads for multiturn cases
│           └── openclaw_workspace_snapshot--*.tar.gz
└── evaluations/suit_<suite_id>/
    └── evaluation_profile_<fp6>/eval_profile_<eval_id>_<fp6>/
        └── <model_id>/<case_id>/
            ├── evaluation_result_summary_1.md      ← START HERE: verdict + evidence
            ├── judge_1.prompt.debug.md             ← exact prompt the judge saw
            └── raw_outputs/
                ├── final_result_1.json             ← judge score + deterministic summaries
                ├── judge_1.json                    ← raw aggregated judge response
                └── judge_1.prompt.user.json        ← structured subject view payload
```

**Reading order:**
1. `evaluation_result_summary_1.md` — final score, judge evidence, dimension breakdown
2. `judge_1.prompt.debug.md` — what the judge actually saw (check here if a score seems wrong)
3. `raw_outputs/final_result_1.json` — judge scores, deterministic summaries, and final reported dimensions
4. `run_1.json` — full event trace (tool calls, messages, token usage) for runner-level debug
5. For openclaw: `run_1.artifacts/openclaw_workspace_diff--*.diff` — the exact changes the agent made to the workspace

---

## Custom OpenClaw agents

The shipped examples use `basic_agent`. To benchmark your own agent — with its own identity, instructions, and context files — create an entry under `configs/agents/<agent_id>/`:

```
configs/agents/my_agent/
  agent.yaml          ← agent ID, openclaw config fragments
  workspace/
    AGENTS.md         ← workspace rules and session behaviour (required)
    SOUL.md           ← agent personality and values
    IDENTITY.md       ← name, role, avatar
    USER.md           ← context about the person the agent works for
    TOOLS.md          ← environment-specific tool notes
    BOOTSTRAP.md      ← first-run setup instructions (deleted after first session)
    HEARTBEAT.md      ← idle/heartbeat response instructions
```

The workspace is copied into an ephemeral directory before each run. The agent sees it as its home. Any file you add here shapes its behaviour; changing a file invalidates the fingerprint for that agent, so all stored runs for it are re-executed on the next campaign.

**Do not set `agent.prompt` in `agent.yaml` unless you intend to test a modified configuration.** Omitting it is the correct default. OpenClaw has its own internal system prompt that is separate from the workspace files — those files are context the agent reads, not the system prompt itself. Setting `agent.prompt` replaces that internal prompt, which modifies the OpenClaw harness and means you are no longer benchmarking the same agent your users interact with.

Then wire the agent into your run profile:

```yaml
# configs/run_profiles/my_run.yaml
openclaw:
  agent_id: my_agent
  image: ghcr.io/openclaw/openclaw:2026.4.15
  timeout_seconds: 300
```

See `skill/references/openclaw-agents.md` for workspace file roles, the full `agent.yaml` schema, and how to capture a workspace from a live OpenClaw instance.

---

## Common recipes

### Add a new model

Add to `models:` in the suite YAML and re-run. Only the new model's cases execute.

### Add a new test case

Create `configs/cases/<new_case_id>/test.yaml` or `configs/cases/<group>/<new_case_id>/test.yaml`, add the ID to `case_selection.include_case_ids`, re-run.

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
  cases/<group>/<case_id>/test.yaml
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
- `skill/references/openclaw-agents.md` — creating and customising OpenClaw agents, workspace file roles, run artifacts
- `uv run mkdocs serve` — browse the full documentation site locally
