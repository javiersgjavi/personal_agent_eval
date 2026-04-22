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
   Use `web_search` to find the official Python documentation page about the current stable version.
   Then give me a short answer with:
   - the title or page you found
   - the official URL you consulted
   - one sentence explaining why that source is reliable

Expectations
Hard
- Uses web_search instead of relying only on training memory.
- Includes an official Python source URL in the final answer.
Soft
- Response is concise and readable.

Rubric (optional guidance) — overall score 0–10

Scale anchors
| Score | Meaning |
|------:|---------|
| 10 | Uses web_search and cites an official Python URL; concise, correct, and justified. |
| 7 | Meets the essentials but is missing minor details or clarity. |
| 4 | Partially meets the task; weak sourcing or unclear answer. |
| 0 | No attempt / irrelevant / empty output. |

Criteria
| Criterion | What “high” looks like | What “low” looks like |
|---|---|---|
| Task completion | Includes the requested title/page, an official URL, and a brief reliability justification. | Missing key requested items (e.g., no official URL). |
| Evidence grounding | Uses web_search and bases claims on retrieved evidence. | Relies on training memory or makes unsupported claims. |
| Clarity and brevity | Short, readable bullets; no unnecessary text. | Verbose or hard to scan. |

Scoring instruction
- Use this rubric to set overall.score. If a hard expectation or deterministic check fails, cap overall.score (typically <= 4). Cite 1–3 decisive facts in overall.evidence.

Deterministic checks
- llm-probe-browser-example-final: final_response_present [task]

SUBJECT RESPONSE
Tool activity: 6 tool calls; tools used: web_search

EXECUTION EVIDENCE
Deterministic summary: passed_checks=0, failed_checks=1, error_checks=0, total_checks=1
Material failures
- Tool-enabled conversation exceeded max_turns=6 without a final answer.

Process trace
1. tool_call
   tool: web_search
   {
     "query": "official Python documentation current stable version"
   }
2. tool_result
   tool: web_search
   status: success
   output: search_results
   query: official Python documentation current stable version
   result_count: 5
   top_titles: Python 3.14.4 documentation, Download Python | Python.org, The Latest Version of Python | phoenixNAP KB, Python Versions — Python - from None to AI, Python Latest Version - Release History, LTS & EOL
3. message
   role: tool
   {"status": "success", "output": {"query": "official Python documentation current stable version", "results": [{"title": "Python 3.14.4 documentation", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F&rut=11c6e9b754896883f7ce060b8c90bf5f4d36b3f54a0ba40deb43f14760a0d753"}, {"title": "Download Python | Python.org", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdownloads%2F&rut=8eeb7485d096017ada98c2f191d27b942be4853d7dd1c06ab527a92729746fe5"}, {"title": "The Latest Version of Python | phoenixNAP KB", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fphoenixnap.com%2Fkb%2Flatest%2Dpython%2Dversion&rut=78e27870118f1333fb8483842fd736ef24f7d91e654b4f6c443803d2ed61cc1e"}, {"title": "Python Versions — Python - from None to AI", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fpython3.info%2Fabout%2Fversions.html&rut=7367243ca8418b86e2e160bfc6a4a2bbe51d083e0b5392b6c596ca47f14482e6"}, {"title": "Python Latest Version - Release History, LTS & EOL", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fversionlog.com%2Fpython%2F&rut=55a91ca724f4d3744cc7323b5e67a43c8658623586fc7fcd850a6cd69d0fed50"}]}}
4. tool_call
   tool: web_search
   {
     "query": "current stable Python version docs.python.org"
   }
5. tool_result
   tool: web_search
   status: success
   output: search_results
   query: current stable Python version docs.python.org
   result_count: 5
   top_titles: Python 3.14.4 documentation, Status of Python versions, Python Versions — Python - from None to AI, The Latest Version of Python | phoenixNAP KB, Download Python | Python.org
6. message
   role: tool
   {"status": "success", "output": {"query": "current stable Python version docs.python.org", "results": [{"title": "Python 3.14.4 documentation", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F&rut=11c6e9b754896883f7ce060b8c90bf5f4d36b3f54a0ba40deb43f14760a0d753"}, {"title": "Status of Python versions", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdevguide.python.org%2Fversions%2F&rut=8d3cdbd7682efebbe6cba4ddef2822d5fe4cd002ab47540cec1e05ec349c9695"}, {"title": "Python Versions — Python - from None to AI", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fpython3.info%2Fabout%2Fversions.html&rut=7367243ca8418b86e2e160bfc6a4a2bbe51d083e0b5392b6c596ca47f14482e6"}, {"title": "The Latest Version of Python | phoenixNAP KB", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fphoenixnap.com%2Fkb%2Flatest%2Dpython%2Dversion&rut=78e27870118f1333fb8483842fd736ef24f7d91e654b4f6c443803d2ed61cc1e"}, {"title": "Download Python | Python.org", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdownloads%2F&rut=8eeb7485d096017ada98c2f191d27b942be4853d7dd1c06ab527a92729746fe5"}]}}
7. tool_call
   tool: web_search
   {
     "query": "\"Python 3.14\""
   }
8. tool_result
   tool: web_search
   status: success
   output: search_results
   query: "Python 3.14"
   result_count: 5
   top_titles: Python Release Python 3.14.0 | Python.org, Python 3.14: Cool New Features for You to Try - Real Python, Python 3.14's best new features - Python Morsels, An Intro to Python 3.14's New Features - Mouse Vs Python, What's New in Python 3.14 | Better Stack Community
9. message
   role: tool
   {"status": "success", "output": {"query": "\"Python 3.14\"", "results": [{"title": "Python Release Python 3.14.0 | Python.org", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdownloads%2Frelease%2Fpython%2D3140%2F&rut=854ab0cc0e06af9b165e28668e4bb4df3c74c8e0b3bdc22a3227edafd2f688b7"}, {"title": "Python 3.14: Cool New Features for You to Try - Real Python", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Frealpython.com%2Fpython314%2Dnew%2Dfeatures%2F&rut=fe058f3114b7e1f120c4206515753dbd01fd4140d62ec92f1e538d528488eec0"}, {"title": "Python 3.14's best new features - Python Morsels", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.pythonmorsels.com%2Fpython314%2F&rut=79935f72d76e4d528ada6968d9b36f7e6682853a688edd8dc702dc8b9c3f6149"}, {"title": "An Intro to Python 3.14's New Features - Mouse Vs Python", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fblog.pythonlibrary.org%2F2025%2F10%2F09%2Fan%2Dintro%2Dto%2Dpython%2D3%2D14s%2Dnew%2Dfeatures%2F&rut=d5bedf5622cfb99adada9ea6f202fbfd0909e952511305680343802bac6a1679"}, {"title": "What's New in Python 3.14 | Better Stack Community", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fbetterstack.com%2Fcommunity%2Fguides%2Fscal
   ... [truncated]
10. tool_call
   tool: web_search
   {
     "query": "site:docs.python.org Python 3.14 documentation"
   }
11. tool_result
   tool: web_search
   status: success
   output: search_results
   query: site:docs.python.org Python 3.14 documentation
   result_count: 5
   top_titles: ▷ Curso de programación Python - Online - Escuela MUSK, manual de python en Amazon - manual de python a Precios Bajos, Python 3.14.4 documentation, What's new in Python 3.14 — Python 3.14.3 documentation, Built-in Functions — Python 3.14.3 documentation
12. message
   role: tool
   {"status": "success", "output": {"query": "site:docs.python.org Python 3.14 documentation", "results": [{"title": "▷ Curso de programación Python - Online - Escuela MUSK", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fduckduckgo.com%2Fy.js%3Fad_domain%3Demagister.com%26ad_provider%3Dbingv7aa%26ad_type%3Dtxad%26click_metadata%3De4YOB5v05GMXW5IgQsZLWnPWssTlLFP3_h6tpnCKjxOHmNiDS28NOmUJasN%252DDHolHEBIZsdenQB9tTz627CTkUEyoNxQfdmMgdefrxBaQIAPi39KFLiMh1iZfYdW4fbGWmUAbVyo7FXPZuwNfQfoAaSd39FGiwYnAKkTq_jbBKM.1gFT9H6iVYeJBp25y5UWkw%26rut%3D0e6b1723c05d701cc223ee6e53680127839b7cc786530be664b595a4a0a6e526%26u3%3Dhttps%253A%252F%252Fwww.bing.com%252Faclick%253Fld%253De8CeuXZPJL46XnerMaIE6GnjVUCUy2JcHaMJe0pgCmzL3ev3IjufqBMyn87GL6fbtwWXtwKQLxDcGs5FxWXbvI8xjsBT15al2M9OPBTd_sjG7LhiNVecOWsPcj7lhnbZ9Av5Wj6rUA%252DG%252DKOVWyV%252Dy1uL_z2UqUmI0n18Oxp40fd4YDuQ2WFAytOAtuuoYBa78H_dPgQoCmoud7X4_KexGSNp6O80g%2526u%253DaHR0cHMlM2ElMmYlMmZ3d3cuZW1hZ2lzdGVyLmNvbSUyZmN1cnNvLXByb2dyYW1hY2lvbi1weXRob24tY3Vyc29zLTM3ODM5OTcuaHRtJTNmcGZpY2hhcyUzZDI1Mjg4JTI2T1ZSQVclM2RFbWFnaXN0ZXJfQmluZ0FkcyUyNmNhbXBhaWduaWQlM2QzNjc3MzU1NTYlMjZhZGdyb3VwaWQlM2QxMjEyNzYxNzcyNTg5NTI1JTI2bWF0Y2h0eXBlJTNkYiUyNm5ldHdvcmslM2RnJTI2ZGV2aWNl
   ... [truncated]
13. tool_call
   tool: web_search
   {
     "query": "\"Python 3.14.4\""
   }
14. tool_result
   tool: web_search
   status: success
   output: search_results
   query: "Python 3.14.4"
   result_count: 0
15. message
   role: tool
   {"status": "success", "output": {"query": "\"Python 3.14.4\"", "results": []}}
16. tool_call
   tool: web_search
   {
     "query": "latest Python version stable release 2025"
   }
17. tool_result
   tool: web_search
   status: success
   output: search_results
   query: latest Python version stable release 2025
   result_count: 5
   top_titles: Status of Python versions, Python Latest Version - Release History, LTS & EOL, Latest Python Version (2025) - What's New in Python 3.14?, The Latest Version of Python | phoenixNAP KB, Python 3.14 Released and Other Python News for November 2025
18. message
   role: tool
   {"status": "success", "output": {"query": "latest Python version stable release 2025", "results": [{"title": "Status of Python versions", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdevguide.python.org%2Fversions%2F&rut=8d3cdbd7682efebbe6cba4ddef2822d5fe4cd002ab47540cec1e05ec349c9695"}, {"title": "Python Latest Version - Release History, LTS & EOL", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fversionlog.com%2Fpython%2F&rut=55a91ca724f4d3744cc7323b5e67a43c8658623586fc7fcd850a6cd69d0fed50"}, {"title": "Latest Python Version (2025) - What's New in Python 3.14?", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.liquidweb.com%2Fblog%2Flatest%2Dpython%2Dversion%2F&rut=6b1fb4e5dcc6680d5ec244ed2c5d537836a248db4346f901a2175414be95707b"}, {"title": "The Latest Version of Python | phoenixNAP KB", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fphoenixnap.com%2Fkb%2Flatest%2Dpython%2Dversion&rut=78e27870118f1333fb8483842fd736ef24f7d91e654b4f6c443803d2ed61cc1e"}, {"title": "Python 3.14 Released and Other Python News for November 2025", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Frealpython.com%2Fpython%2Dnews%2Dnovember%2D2025%2F&rut=0afd8023dd06e312b53cc536948cc9136ee55bc161c7edf904d
   ... [truncated]
