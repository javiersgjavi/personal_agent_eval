# Runnable Examples

This repository ships two small example campaigns that are meant to be copied, adapted, and run as
they are.

Both examples are intentionally fixed to:

- run model: `minimax/minimax-m2.7`
- judge model: `openai/gpt-5.4-mini`

They each include two cases:

- one case that requires real tool use
- one case that requires browser or web-search use

## llm_probe example campaign

Files:

- cases:
  - `configs/cases/llm_probe_tool_example/test.yaml`
  - `configs/cases/llm_probe_browser_example/test.yaml`
- suite: `configs/suites/llm_probe_examples.yaml`
- run profile: `configs/run_profiles/llm_probe_examples.yaml`
- evaluation profile: `configs/evaluation_profiles/judge_gpt54_mini.yaml`

Run it:

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

## OpenClaw example campaign

Files:

- cases:
  - `configs/cases/openclaw_tool_example/test.yaml`
  - `configs/cases/openclaw_browser_example/test.yaml`
- suite: `configs/suites/openclaw_examples.yaml`
- run profile: `configs/run_profiles/openclaw_examples.yaml`
- evaluation profile: `configs/evaluation_profiles/judge_gpt54_mini.yaml`

Run it:

```bash
uv run pae run-eval \
  --suite openclaw_examples \
  --run-profile openclaw_examples \
  --evaluation-profile judge_gpt54_mini
```

OpenClaw requires Docker access and `OPENROUTER_API_KEY` on the host because the pinned OpenClaw
image is executed inside a container.

## What gets written to `outputs/`

Run artifacts and evaluation artifacts are generated at execution time and are not meant to be
committed to Git.

For one evaluated case, the human-facing files are:

```text
outputs/evaluations/suit_<suite_id>/evaluation_profile_<run_fp6>/eval_profile_<eval_id>_<eval_fp6>/
  <model_id>/
    <case_id>/
      evaluation_result_summary_1.md
      judge_1.prompt.debug.md
      raw_outputs/
        final_result_1.json
        judge_1.json
        judge_1.prompt.user.json
```

The intended reading order is:

1. `evaluation_result_summary_1.md`
2. `judge_1.prompt.debug.md`
3. `raw_outputs/` only if you need the technical payloads
