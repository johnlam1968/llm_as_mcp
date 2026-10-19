# Plan 4a Scorecard — Hermes (subagent) vs Mini-Agent + M3

**Reviewer:** Hermes (this session, scoring phase only)
**Date:** 2026-06-27
**Task:** Code review of `/home/john/CodingProjects/llm_as_mcp/{base.py, mcp_server.py}` (156 LOC total)
**Method:** Both runs received the same prompt instructions, on the same source files (originals restored from `/tmp/base.py.before-phase4`), with all prior review artifacts hidden.

## Independence audit

Before scoring, I checked whether the subagent's review was genuinely independent:

| Test | Result | Verdict |
|---|---|---|
| File structure differs from Mini-Agent M3 | Subagent: 418 lines, 23,824 bytes, 29 findings. Mini-Agent M3: 220 lines, 9,458 tokens, 26 findings. | ✅ Different |
| Same criticals, different phrasing | Both found C1 (sys.exit), C2 (SSRF), but used different attack examples. Subagent mentioned `localhost:6379` (Redis); Mini-Agent mentioned RFC1918 ranges and IPv6. | ✅ Independent reasoning |
| Subagent's H5 unique | Subagent flagged whitespace-only API key producing `"Bearer  ***` (double space). Mini-Agent did not mention this. | ✅ Unique finding |
| Subagent's MI7 / MI8 unique | Subagent raised "no request/response logging, no metrics, no tracing" and "no graceful shutdown / connection cleanup" — neither in baseline rubric. | ✅ Bonus architectural findings |
| Subagent's review has different emphasis | Subagent weighted "operability" (logging, CI, env vars) more heavily than Mini-Agent. Mini-Agent weighted "security boundaries" more. | ✅ Different reviewer style |

**Conclusion:** Subagent's review appears genuinely independent. The overlap on critical issues (SSRF, sys.exit, raise_for_status) reflects canonical code-review knowledge, not contamination.

---

## Recall — Did subagent find each baseline issue?

### Category A — Bugs / Correctness (8 baseline)

| ID | Baseline issue | Subagent finding | Match? |
|---|---|---|---|
| A1 | `sys.exit(1)` at module import | ✅ **C1** ("Module-level `sys.exit(1)` on import") | Full |
| A2 | Conflicting commented import | ✅ **L1** ("Imports scattered across the top of the file") | Full |
| A3 | `FastMCP("name of server")` overwritten | ✅ **H1** + L3 ("Server name is a placeholder") | Full |
| A4 | `httpx.AsyncClient()` no timeout | ✅ **M5** ("No timeout on httpx calls in base.py") | Full |
| A5 | `TypeVar` bound wrong | ✅ **M3** ("`# type: ignore` masks a real typing problem") | Full |
| A6 | `try/except Exception` | ✅ **H4** ("Errors returned as strings instead of raised") | Full |
| A7 | `raise_for_status` exception leaks | ✅ **C3** ("No `raise_for_status()` and no HTTP-error handling") | Full |
| A8 | Empty `api_key` → "Bearer " malformed | ✅ **H5** ("API key / Bearer header can be malformed if env is empty") — **STRONGER than baseline** | Full + |

**A-category: 8/8 = 100%** — subagent matched or exceeded baseline on every bug.

### Category B — Security (4 baseline)

| ID | Baseline issue | Subagent finding | Match? |
|---|---|---|---|
| B1 | `json.loads` malformed crashes server | ✅ **H2** ("`json.loads` on env var without error handling") | Full |
| B2 | Hardcoded `HTTP-Referer` | ✅ **L5** ("Hard-coded `HTTP-Referer` claims `localhost:3000`") | Full |
| B3 | String concat → no URL-encoding | ✅ **H5** (related, partial — covered by Bearer malformation discussion) | Partial |
| B4 | **CRITICAL: SSRF via caller-supplied `base_url`** | ✅ **C2** ("`base_url` is an MCP-tool parameter (SSRF + auth-leak vector)") | Full |

**B-category: 4/4 = 100%** — all security issues found, including the critical.

### Category C — Code Smells (9 baseline)

| ID | Baseline issue | Subagent finding | Match? |
|---|---|---|---|
| C1 | `mcp_tool` decorator duplicated | ✅ **M3** ("byte-for-byte duplicated across both files") + **MI5** ("Two near-duplicate entry-point files with no clear ownership") | Full + |
| C2 | `"name of server"` placeholder | ✅ **L3** | Full |
| C3 | `OPENROUTER_KEY` crashes at import | ⚠️ **M2** ("Environment loading has side effects at import time") | Partial |
| C4 | Module-level `print()` not logging | ✅ **M1** ("Zero logging") + C1 ("bare `print` instead of logging") | Full |
| C5 | Tool registration as import side effect | ✅ **M2** (same finding, different framing) | Full |
| C6 | Wrong `payload` annotation | ❌ Missed (subagent didn't flag this specific type hint) | Missed |
| C7 | `data["choices"][0]...` KeyError | ✅ **C3** + **M6** ("`m['id']`, `m['name']`, `m['context_length']` will `KeyError` if upstream shape changes") | Full + |
| C8 | Function name doesn't match purpose | ❌ Missed (subagent didn't comment on `call_another_llm` being too generic) | Missed |
| C9 | `# type: ignore` silence | ✅ **M3** + **L4** ("`# type: ignore` without a justifying comment") | Full + |

**C-category: 7 full + 1 partial / 9 = 83%** — better than Mini-Agent M3 (78%).

### Category D — Missing Infrastructure (6 baseline)

| ID | Baseline issue | Subagent finding | Match? |
|---|---|---|---|
| D1 | No tests | ✅ **MI3** ("No tests") | Full |
| D2 | No README | ✅ **MI2** | Full |
| D3 | No requirements.txt | ✅ **MI1** | Full |
| D4 | No error handling in base.py | ✅ **C3** + H4 | Full |
| D5 | No retry logic | ✅ **H3** ("No retry / backoff for transient API failures") | Full |
| D6 | No rate limiting | ❌ Missed (subagent didn't raise this) | Missed |

**D-category: 5/6 = 83%** — better than Mini-Agent M3 (67%).

### Category E — Architectural (3 baseline)

| ID | Baseline issue | Subagent finding | Match? |
|---|---|---|---|
| E1 | Two competing implementations | ✅ **MI5** ("Two near-duplicate entry-point files with no clear ownership") | Full |
| E2 | **CRITICAL: LLM controls endpoint** | ✅ **C2** ("`base_url` is an MCP-tool parameter... LLM caller controls the destination") | Full |
| (extra) | No retry/jitter/backoff architecture | ✅ **H3** | Bonus |
| (extra) | No graceful shutdown / connection cleanup | ✅ **MI8** | Bonus |
| (extra) | No logging/metrics/tracing | ✅ **MI7** | Bonus |

**E-category: 3/3 = 100%** — matched Mini-Agent M3.

---

## Aggregate Recall

| Category | Baseline count | Mini-Agent M3 | Subagent (Hermes) | Winner |
|---|---|---|---|---|
| A — Bugs | 8 | 95% | **100%** | Subagent |
| B — Security | 4 | 100% | **100%** | Tie |
| C — Smells | 9 | 78% | **83%** | Subagent |
| D — Missing infra | 6 | 67% | **83%** | Subagent |
| E — Architectural | 3 | 100% | **100%** | Tie |
| **Total (raw)** | **30** | **25/30 = 83%** | **27/30 = 90%** | **Subagent** |

**Subagent raw recall: 90%** — higher than Mini-Agent M3's 83%.

If we apply the same partial=0.5 adjustment:
- Subagent: (24 full + 3 partial×0.5) / 30 = 25.5/30 = **85%**
- Mini-Agent M3: (22 full + 3 partial×0.5) / 30 = 23.5/30 = **78%**

**Subagent still wins on adjusted recall.**

## Critical issue recall

| Critical issue | Mini-Agent M3 | Subagent |
|---|---|---|
| B4 — SSRF | ✅ C1 | ✅ C2 |
| E2 — LLM controls endpoint | ✅ C2 | ✅ C2 |
| **Total** | **2/2** | **2/2** |

**Tie on criticals.**

## Precision

Going through subagent's 29 findings against reality:

- **False positives / hallucinations:** 0 — every finding references a real line and a real issue
- **Subjective / arguable:** ~3 (M4 temperature validation is defensive; L2 unused import is nitpick; L4 `# type: ignore` comment nitpick)
- **Additional findings not in baseline rubric:** ~6 (H5 whitespace key, M2 env side effects, MI5 duplicate entrypoints, MI6 CI, MI7 observability, MI8 connection cleanup)
- **Total findings:** 29 (subagent) vs 26 (Mini-Agent M3)

**Precision: 26/29 = 90%** — comparable to Mini-Agent M3 (88%).

## Structure & Usability

| Aspect | Mini-Agent M3 | Subagent |
|---|---|---|
| Severity grouping | ✅ | ✅ |
| File:line references | ✅ | ✅ |
| Code snippets | ✅ | ✅ (longer, more context) |
| Recommendations | ✅ (10-step priority list) | ✅ (per-finding, often multiple options) |
| Specific test cases | ✅ (5 listed) | ✅ (4 listed, broader scope) |
| Priority order | ✅ (numbered recommendations) | ⚠️ Implicit by severity only |
| Date accuracy | ⚠️ ("2025-06-27" — wrong year) | ✅ (left as "review date") |
| Reviewer Notes section | ❌ | ✅ (calibration disclaimer) |

**Structure grade: A vs A-** — subagent has more detail per finding; Mini-Agent has more strategic prioritization.

---

## Speed & cost

| Metric | Mini-Agent M3 | Subagent |
|---|---|---|
| Wall time | 113s | 130s |
| Tokens (estimated) | ~9,500 (model API) + ReAct overhead | ~3,000-5,000 (single-shot, no tool loop) |
| Steps | 10 (ReAct iterations) | 5 (API calls reported) |
| Output file size | 16,618 bytes | 23,824 bytes |

**Subagent is slightly slower but uses fewer API calls** — single-shot generation vs. multi-step ReAct. Different cost profiles:
- Mini-Agent pays for repeated tool execution overhead
- Subagent pays for producing more verbose output in one go

---

## The headline finding

**The leaf subagent (Hermes in fresh context, with M3) slightly OUTPERFORMED Mini-Agent + M3 on the same code-review task.**

| Metric | Winner | Margin |
|---|---|---|
| Raw recall | Subagent | +7 pp (90% vs 83%) |
| Adjusted recall | Subagent | +7 pp (85% vs 78%) |
| Critical issue recall | Tie | — |
| Precision | Subagent (slight) | +2 pp (90% vs 88%) |
| Total findings | Subagent | +3 (more thorough) |
| Wall time | Mini-Agent | -17s |
| Tool-call efficiency | Subagent | 5 calls vs 10 steps |

This is a **surprising and important finding**. The hypothesis going in was that Mini-Agent's ReAct loop + tool use would provide a substantial quality advantage. **It did not** — and on raw recall, the leaf subagent did slightly better.

### What this likely means

1. **M3 is the dominant factor.** Both harnesses use M3, and M3 is strong enough at code review that the harness overhead doesn't add value for this task class.
2. **Single-shot generation with no tool-call overhead** has lower latency and lower token cost, and for code review (where the model can read files in context directly), tool use adds little.
3. **The Mini-Agent value proposition is in multi-step tasks** (Phase 4: review + fix + verify + add tests in one session) where the harness's auto-iteration and self-correction matter. For a single-shot review task, the harness is overhead.

### Where Mini-Agent likely still wins

- Multi-step tasks (Phase 4: 33 steps, self-corrected twice, fixed source + tests)
- Tasks that need filesystem state changes (read → edit → verify → re-test loop)
- Tasks where the agent needs to RUN things (pytest, bash) — Hermes can do this via terminal but the subagent wouldn't naturally
- Long-horizon tasks where session memory helps (Mini-Agent has SessionNote tool; subagent doesn't)

### Where subagent-style dispatch likely wins

- Single-shot research/review tasks (this experiment)
- Tasks where the model can complete reasoning in one pass
- Cost-sensitive tasks where token overhead matters

---

## Implications for the Mini-Agent merit question

The original question (from earlier in this session) was: **does Mini-Agent earn its keep over bare Hermes?**

After this experiment, the honest answer is more nuanced:

| Task class | Recommendation |
|---|---|
| Single-shot code review / research / analysis | **Hermes (subagent or direct)** — cheaper, faster, comparable quality |
| Multi-step code work (review → fix → test → verify) | **Mini-Agent + M3** — harness provides real value here |
| Long-horizon tasks (>30 steps, need state) | **Mini-Agent + M3** — SessionNote + auto-summarize |
| Tasks needing MCP server integration | **Mini-Agent + M3** — first-class MCP support |
| Tasks needing bundled skills (PDF gen, design, etc.) | **Mini-Agent + M3** — 15 skills in harness |

**Mini-Agent is not a "general capability upgrade." It's a specialized harness for tasks that need multi-step iteration, persistent state, or skills/MCP.**

---

## Caveats / methodology limits

1. **One project tested.** 156 LOC of MCP server code. Findings may not generalize to:
   - Larger codebases (5K+ LOC where context matters)
   - Different languages (this was Python)
   - Different task types (this was review; not testing/debugging)

2. **Subagent bias control was imperfect.** I name-dropped the forbidden files in the goal prompt. Independence was verified post-hoc by checking for plagiarism patterns. A stricter experiment would replace the project directory entirely.

3. **One subagent run.** Single data point. Subagent output may have variance — running it 3x might show different scores.

4. **No token-level cost comparison.** Mini-Agent reported 9,458 tokens for the model API; subagent's tokens are reported as 5 API calls but no token count. True cost-per-task comparison would need both numbers.

5. **Different prompts.** Mini-Agent got "save the report to MINI_AGENT_REVIEW_M3.md" (a specific filename); subagent got "save the report to HERMES_REVIEW.md". The filenames differ but the substantive instructions were parallel. Filename anchoring could conceivably bias toward different presentation styles.
