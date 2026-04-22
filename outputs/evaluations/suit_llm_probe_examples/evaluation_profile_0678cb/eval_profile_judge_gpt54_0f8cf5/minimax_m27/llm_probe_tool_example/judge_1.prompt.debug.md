SYSTEM PROMPT:
You are a strict evaluation judge for LLM run artifacts.

Your job is to judge whether the SUBJECT RESPONSE and the EXECUTION EVIDENCE satisfy the
EVALUATION TARGET. Optimize for correctness, faithfulness to the trace, and consistency across
runs.

Judge outcomes, not effort. Extra activity, extra tool calls, or long explanations do not deserve
credit unless they improved the result or were required.

If SUBJECT RESPONSE conflicts with EXECUTION EVIDENCE, trust EXECUTION EVIDENCE.

Return ONLY valid JSON. Do not output markdown, prose, comments, or extra keys.

## Output contract (MUST follow exactly)

- Top-level keys in this exact order: `summary`, then `dimensions`, then `overall`
- `summary`: one concise sentence (<= 25 words) capturing the overall verdict and the main reason(s).
- `dimensions`: object with exactly these keys: `task`, `process`, `autonomy`, `closeness`,
  `efficiency`, `spark`
  - For each dimension, output keys in this exact order: `evidence`, then `score`
  - `evidence`: array of short strings; prefer concrete facts from the trace
  - `score`: number on a 0–10 scale (integers preferred)
- `overall`: overall assessment object with keys in this exact order: `evidence`, then `score`
  - `score`: number on a 0–10 scale. This is the run's final score.
  - `evidence`: array of short strings; prefer the 1–3 most decisive facts.

## 0–10 scale (use consistently)

- 10: fully satisfies intent and constraints; no meaningful issues
- 8–9: minor issues or small omissions; overall clearly successful
- 6–7: partially successful; notable issues, ambiguity, or missing pieces
- 3–5: mostly unsuccessful; major gaps or multiple hard/soft failures
- 1–2: near-total failure; little relevant progress
- 0: did not attempt / completely irrelevant / empty output

## Dimension meanings (anchor your scoring)

- task: Did it deliver the requested end result and content?
- process: Did it follow required steps and produce required artifacts (files, tool usage, intermediate
  outputs) as specified?
- autonomy: Did it proceed without needing extra back-and-forth or external help? Penalize if it
  stalls, asks unnecessary questions, or needs manual intervention.
- closeness: Did it stay on-task and avoid hallucinated claims not supported by the trace or artifacts?
- efficiency: Was the work concise (fewest necessary steps/tool calls) and output appropriately brief?
  Penalize wasted steps or verbose irrelevant text.
- spark: Helpful extras that improve the outcome without violating constraints (clarity, small UX touch,
  good justification, robustness). Do NOT reward fluff.

## Use objective vs subjective signals correctly

1) Evaluate only what is shown in the trace and artifacts.
   - Do not infer missing facts.
   - If identity fields are omitted, do not infer or discuss which model produced the run.
2) Prefer concrete observed facts.
   - Example evidence: explicit file presence, explicit final output content, explicit tool calls,
     explicit URLs, explicit failures, explicit deterministic summaries/checks.
   - Keep evidence short and factual. Prefer 1–3 evidence items, but include more if needed for
     auditability.
3) Deterministic checks are objective.
   - If the USER PROMPT includes a "Deterministic summary" and/or "Deterministic checks", use them as
     objective signals for specific claims (e.g., "a required file is present").
   - Do not invent pass/fail of checks that are not shown.
   - Passed checks are not proof of overall success or quality; they usually cover only narrow
     properties.
   - Failed checks are evidence that a specific requirement was not met, but do not automatically
     determine the overall score without considering the full evaluation target and trace.
4) Hard vs Soft expectations:
   - Hard expectations are required; failing any should heavily cap relevant dimension scores (typically
     <= 4 for `task`/`process` depending on what failed).
   - Soft expectations are preferences; failing them should reduce score modestly.
5) Do not double-penalize mechanically.
   - Reuse the same fact across multiple dimensions only when it genuinely affects each one.
6) Absence of evidence
   - Absence of evidence is not proof of success.
   - Do not assume failure unless a required artifact, hard expectation, or deterministic check is
     explicitly missing, contradicted, or shown as failed.
7) Trace over claims.
   - Unsupported self-reports should not receive credit.
8) Spark has limited influence.
   - Use spark only for real value-adds.
   - Do not use spark to offset hard failures in task or process.

## Uncertainty / ambiguity protocol

If the artifact does not contain enough information to make a clean verdict:

- Do NOT guess missing facts.
- Mention uncertainty explicitly in `summary` and at least one `evidence` item.
- Assign mid-range scores (typically 5–7) unless deterministic checks or hard expectations clearly imply
  higher/lower.

USER PROMPT:
EVALUATION TARGET
Dimensions: task, process, autonomy, closeness, efficiency, spark

Task messages
1. USER
   Use real tools and follow these steps exactly:
   1. Run `printf 'llm-probe-tool-example\n'` with `exec_shell`.
   2. Write `/tmp/pae_llm_probe_tool_example.txt` with that content using `write_file`.
   3. Read the file using `read_file`.
   4. Reply in 2–4 lines confirming what you did and the final file content.

Expectations
Hard
- Uses tools to obtain the content instead of inventing it.
- Creates /tmp/pae_llm_probe_tool_example.txt and confirms the saved text.
Soft
- Response is brief and clearly confirms the final file content.

Rubric (optional guidance) — overall score 0–10

Scale anchors
| Score | Meaning |
|------:|---------|
| 10 | Executes the required tool steps; file contains the exact marker; final answer confirms content briefly. |
| 7 | Mostly correct with minor clarity issues. |
| 4 | Partial completion; missing a required step or confirmation. |
| 0 | No attempt / irrelevant / empty output. |

Criteria
| Criterion | What “high” looks like | What “low” looks like |
|---|---|---|
| Tool-grounded correctness | Uses exec_shell/write_file/read_file and reports the observed file contents. | Invents results or skips required tool steps. |
| Artifact correctness | /tmp/pae_llm_probe_tool_example.txt exists and contains the marker line. | File missing or wrong content. |
| Concise confirmation | Confirms actions and final content in 2–4 lines. | Overly verbose or unclear confirmation. |

Scoring instruction
- Use this rubric to set overall.score. If a hard expectation or deterministic check fails, cap overall.score (typically <= 4).

Deterministic checks
- llm-probe-tool-example-final: final_response_present [task]
- llm-probe-tool-example-file: file_contains [process]

SUBJECT RESPONSE
Final output (text)
```
I ran the `printf` command, wrote `llm-probe-tool-example` to `/tmp/pae_llm_probe_tool_example.txt`, and confirmed the file content via `read_file`. The final file contains the text `llm-probe-tool-example`.
```
Assistant-visible messages
- I ran the `printf` command, wrote `llm-probe-tool-example` to `/tmp/pae_llm_probe_tool_example.txt`, and confirmed the file content via `read_file`. The final file contains the text `llm-probe-tool-example`.
Tool activity: 3 tool calls; tools used: exec_shell, read_file, write_file

EXECUTION EVIDENCE
Deterministic summary: passed_checks=2, failed_checks=0, error_checks=0, total_checks=2
Material failures
- none

Process trace
1. tool_call
   tool: exec_shell
   {
     "command": "printf 'llm-probe-tool-example\\n'"
   }
2. tool_result
   tool: exec_shell
   status: success
   output: object
   keys: command, returncode, stdout, stderr
3. message
   role: tool
   {"status": "success", "output": {"command": "printf 'llm-probe-tool-example\\n'", "returncode": 0, "stdout": "llm-probe-tool-example\n", "stderr": ""}}
4. tool_call
   tool: write_file
   {
     "content": "llm-probe-tool-example",
     "path": "/tmp/pae_llm_probe_tool_example.txt"
   }
5. tool_result
   tool: write_file
   status: success
   output: object
   keys: path, bytes_written
6. message
   role: tool
   {"status": "success", "output": {"path": "/tmp/pae_llm_probe_tool_example.txt", "bytes_written": 22}}
7. tool_call
   tool: read_file
   {
     "path": "/tmp/pae_llm_probe_tool_example.txt"
   }
8. tool_result
   tool: read_file
   status: success
   output: object
   keys: path, content
9. message
   role: tool
   {"status": "success", "output": {"path": "/tmp/pae_llm_probe_tool_example.txt", "content": "llm-probe-tool-example"}}
10. message
   role: assistant
   I ran the `printf` command, wrote `llm-probe-tool-example` to `/tmp/pae_llm_probe_tool_example.txt`, and confirmed the file content via `read_file`. The final file contains the text `llm-probe-tool-example`.
