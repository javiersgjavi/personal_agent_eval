# Minimal llm_probe Example

This page walks through the shipped `llm_probe` example campaign that lives under `configs/`. You can run it as-is, or use it as a starting point for your own benchmark.

---

## What this example tests

Two cases:

| Case | What it tests |
|---|---|
| `llm_probe_tool_example` | Tool-use chain: `exec_shell` → `write_file` → `read_file` → confirm |
| `llm_probe_browser_example` | Web search grounding: use `web_search` and cite an official URL |

Both cases use `minimax/minimax-m2.7` as the subject model and `openai/gpt-5.4-mini` as the judge.

---

## File layout

| File | Path |
|---|---|
| Tool case | `configs/cases/llm_probe_tool_example/test.yaml` |
| Browser case | `configs/cases/llm_probe_browser_example/test.yaml` |
| Suite | `configs/suites/llm_probe_examples.yaml` |
| Run profile | `configs/run_profiles/llm_probe_examples.yaml` |
| Evaluation profile | `configs/evaluation_profiles/judge_gpt54_mini.yaml` |

---

## Run it

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

---

## The config files explained

### Suite — `configs/suites/llm_probe_examples.yaml`

```yaml
schema_version: 1
suite_id: llm_probe_examples
title: llm_probe runnable examples
models:
  - model_id: minimax_m27
    requested_model: minimax/minimax-m2.7
    label: minimax/minimax-m2.7
case_selection:
  include_case_ids:
    - llm_probe_tool_example
    - llm_probe_browser_example
```

One model, two cases. `model_id` is a local slug used in storage paths; `requested_model` is the OpenRouter model ref.

---

### Run profile — `configs/run_profiles/llm_probe_examples.yaml`

```yaml
schema_version: 1
run_profile_id: llm_probe_examples
title: llm_probe runnable examples
runner_defaults:
  temperature: 0
  timeout_seconds: 90
  max_tokens: 768
  max_turns: 6
  retries: 0
execution_policy:
  max_concurrency: 1
  run_repetitions: 1
  fail_fast: true
  stop_on_runner_error: true
```

`temperature: 0` for determinism. `max_turns: 6` means the model can call tools up to 6 times before the runner forces a final response. `run_repetitions: 1` means one run per case.

---

### Evaluation profile — `configs/evaluation_profiles/judge_gpt54_mini.yaml`

```yaml
schema_version: 1
evaluation_profile_id: judge_gpt54
title: Judge with openai/gpt-5.4-mini
judge_system_prompt_path: prompts/judge_system_default.md
judges:
  - judge_id: gpt54_judge
    type: llm_probe
    model: openai/gpt-5.4-mini
judge_runs:
  - judge_run_id: gpt54_single
    judge_id: gpt54_judge
    repetitions: 1
aggregation:
  method: median
anchors:
  enabled: false
  references: []
security_policy:
  allow_local_python_hooks: false
  network_access: deny
  redact_secrets: true
```

The judge is called once per case. Deterministic checks are preserved as supporting evidence for the judge and for debugging. `redact_secrets: true` strips API keys from the judge prompt.

---

### Tool case — `configs/cases/llm_probe_tool_example/test.yaml`

```yaml
schema_version: 1
case_id: llm_probe_tool_example
title: llm_probe tool example
runner:
  type: llm_probe
input:
  messages:
    - role: user
      content: |
        Use real tools and follow these steps exactly:
        1. Run `printf 'llm-probe-tool-example\n'` with `exec_shell`.
        2. Write `/tmp/pae_llm_probe_tool_example.txt` with that content using `write_file`.
        3. Read the file using `read_file`.
        4. Reply in 2–4 lines confirming what you did and the final file content.
  context:
    llm_probe:
      tools:
        - exec_shell
        - write_file
        - read_file
expectations:
  hard_expectations:
    - text: Uses tools to obtain the content instead of inventing it.
    - text: Creates /tmp/pae_llm_probe_tool_example.txt and confirms the saved text.
  soft_expectations:
    - text: Response is brief and clearly confirms the final file content.
rubric:
  version: 1
  scale:
    min: 0
    max: 10
    anchors:
      "10": Executes all required tool steps; file contains the exact marker; confirmation is brief.
      "7": Mostly correct with minor clarity issues.
      "4": Partial completion; missing a required step or confirmation.
      "0": No attempt / irrelevant / empty output.
  criteria:
    - name: Tool-grounded correctness
      what_good_looks_like: Uses exec_shell/write_file/read_file and reports observed file contents.
      what_bad_looks_like: Invents results or skips required tool steps.
    - name: Artifact correctness
      what_good_looks_like: /tmp/pae_llm_probe_tool_example.txt exists and contains the marker.
      what_bad_looks_like: File missing or wrong content.
    - name: Concise confirmation
      what_good_looks_like: Confirms actions and final content in 2–4 lines.
      what_bad_looks_like: Overly verbose or unclear confirmation.
deterministic_checks:
  - check_id: llm-probe-tool-example-final
    dimensions: [task]
    declarative:
      kind: final_response_present
  - check_id: llm-probe-tool-example-file
    dimensions: [process]
    declarative:
      kind: file_contains
      path: /tmp/pae_llm_probe_tool_example.txt
      text: llm-probe-tool-example
tags:
  - example
  - llm_probe
  - tool_use
```

Key things to notice:
- `input.context.llm_probe.tools` declares which tools the runner exposes to the model
- `rubric` provides the judge with scored anchors and criteria for each dimension
- Two deterministic checks: one for final response presence, one for the exact file content
- The `file_contains` check looks at the **host filesystem** after the llm_probe runner writes the file

---

### Browser case — `configs/cases/llm_probe_browser_example/test.yaml`

```yaml
schema_version: 1
case_id: llm_probe_browser_example
title: llm_probe browser example
runner:
  type: llm_probe
input:
  messages:
    - role: user
      content: |
        Use `web_search` to find the official Python documentation page about the current stable version.
        Then give me a short answer with:
        - the title or page you found
        - the official URL you consulted
        - one sentence explaining why that source is reliable
  context:
    llm_probe:
      tools:
        - web_search
expectations:
  hard_expectations:
    - text: Uses web_search instead of relying only on training memory.
    - text: Includes an official Python source URL in the final answer.
deterministic_checks:
  - check_id: llm-probe-browser-example-final
    dimensions: [task]
    declarative:
      kind: final_response_present
tags:
  - example
  - llm_probe
  - browser
  - web
```

This case only checks for final response presence deterministically. The grounding quality — whether `web_search` was actually used and the URL is real — is assessed by the judge through `hard_expectations`.

---

## What gets written to `outputs/`

The repository commits regenerated artifacts for this example campaign under `outputs/` as reference output, so you can inspect a real example without running the suite first.

```text
outputs/
├── charts/
│   └── judge_gpt54/
│       └── score_cost.png
├── runs/
│   └── suit_llm_probe_examples/
│       └── run_profile_<fp6>/
│           └── minimax_m27/
│               ├── llm_probe_tool_example/
│               │   ├── run_1.json
│               │   └── run_1.fingerprint_input.json
│               └── llm_probe_browser_example/
│                   ├── run_1.json
│                   └── run_1.fingerprint_input.json
└── evaluations/
    └── suit_llm_probe_examples/
        └── evaluation_profile_<fp6>/
            └── eval_profile_judge_gpt54_<fp6>/
                └── minimax_m27/
                    ├── llm_probe_tool_example/
                    │   ├── evaluation_result_summary_1.md  ← start here
                    │   ├── judge_1.prompt.debug.md
                    │   └── raw_outputs/
                    │       ├── final_result_1.json
                    │       ├── judge_1.json
                    │       └── judge_1.prompt.user.json
                    └── llm_probe_browser_example/
                        ├── evaluation_result_summary_1.md
                        ├── judge_1.prompt.debug.md
                        └── raw_outputs/
                            └── ...
```

**Start reading from `evaluation_result_summary_1.md`.** It contains the score, the judge's evidence, and the dimension breakdown in a clean Markdown format.

---

→ [Runnable examples](runnable_examples.md) — both campaigns and their output trees
