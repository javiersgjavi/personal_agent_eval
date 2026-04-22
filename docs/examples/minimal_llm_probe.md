# Minimal llm_probe Example

This repository ships a runnable `llm_probe` example campaign under `configs/`.

## Layout

| Piece | Path |
| --- | --- |
| Tool case | `configs/cases/llm_probe_tool_example/test.yaml` |
| Browser case | `configs/cases/llm_probe_browser_example/test.yaml` |
| Suite | `configs/suites/llm_probe_examples.yaml` |
| Run profile | `configs/run_profiles/llm_probe_examples.yaml` |
| Evaluation profile | `configs/evaluation_profiles/judge_gpt54_mini.yaml` |

The shipped example is intentionally fixed to:

- run model: `minimax/minimax-m2.7`
- judge model: `openai/gpt-5.4-mini`

## Command

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini
```

## What this example demonstrates

- one case that requires local tool use (`exec_shell`, `write_file`, `read_file`)
- one case that requires browser or web search (`web_search`)
- a minimal evaluation path that writes both human-readable and raw outputs

## Output Mental Model

After execution, inspect:

- `evaluation_result_summary_1.md` for the human summary
- `judge_1.prompt.debug.md` for the exact prompt shown to the judge
- `raw_outputs/` for the structured JSON payloads

See [Runnable examples](runnable_examples.md) for the exact output tree.
