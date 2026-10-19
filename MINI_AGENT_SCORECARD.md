# Mini-Agent Phase 2 Scorecard — vs Phase 0 Baseline

**Reviewer:** Hermes
**Date:** 2026-06-27
**Baseline:** `MINI_AGENT_REVIEW_BASELINE.md` (30 issues)
**Mini-Agent output:** `MINI_AGENT_REVIEW.md` (24 issues)

---

## Recall — Did Mini-Agent find each baseline issue?

### Category A — Bugs / Correctness (8 baseline)

| ID | Baseline issue | Mini-Agent finding | Match? |
|---|---|---|---|
| A1 | `sys.exit(1)` at module import | Issue #9 (Unreachable code, line 43-48) catches this in reverse | ⚠️ **Partial** — flagged unreachable code instead of import-time crash. **Missed** that it's a server-crash-on-bad-config bug |
| A2 | Conflicting commented import | Issue #11 (Inconsistent commented imports) | ✅ |
| A3 | `FastMCP("name of server")` overwritten | Issues #1 + #5 (Duplicate instantiation, line 15) | ✅ |
| A4 | `httpx.AsyncClient()` no timeout | Issue #3 (Missing HTTP Timeout, line 50) | ✅ |
| A5 | `TypeVar` bound wrong | Issue #17 (Unused Type Variable) — flagged the var but **missed the wrong bound** | ⚠️ **Partial** |
| A6 | `try/except Exception` swallows all | Issue #4 (Generic Exception Swallowing) | ✅ |
| A7 | `raise_for_status` exception leaks | Not flagged separately — lumped into #4 | ⚠️ **Partial** |
| A8 | Empty `api_key` → "Bearer " malformed | Issue #10 (String Concat header) catches the same vicinity | ⚠️ **Partial** |

**A-category recall:** 3 full + 4 partial / 8 = 7/8 hits (88%), but 5/8 are partial. **Strong but imprecise.**

### Category B — Security (4 baseline)

| ID | Baseline issue | Mini-Agent finding | Match? |
|---|---|---|---|
| B1 | `LLM_API_KEY_DICT` malformed JSON crashes server | Not flagged | ❌ **Missed** |
| B2 | Hardcoded `HTTP-Referer` | Issue #14 (Hardcoded HTTP-Referer) | ✅ |
| B3 | String concat → no URL-encoding | Issue #10 covers the same area | ⚠️ **Partial** |
| B4 | **CRITICAL: SSRF via caller-supplied `base_url`** | **Not flagged** | ❌❌ **Missed (CRITICAL)** |

**B-category recall:** 1 full + 1 partial / 4 = 2/4 hits (50%). **MISSED both critical security issues.**

### Category C — Code Smells (9 baseline)

| ID | Baseline issue | Mini-Agent finding | Match? |
|---|---|---|---|
| C1 | `mcp_tool` decorator duplicated | Not called out as duplication, but the file structure is reviewed | ❌ **Missed the cross-file duplication explicitly** |
| C2 | `"name of server"` placeholder | Issue #1 covers (mentions line 15) | ✅ |
| C3 | `OPENROUTER_KEY` crashes at import | Issue #6 (Hardcoded credentials) flagged env var name, not the crash | ⚠️ **Partial** |
| C4 | Module-level `print()` not logging | Issue #18 (Print for critical error) | ✅ |
| C5 | Tool registration as import side effect | Not flagged | ❌ **Missed** |
| C6 | Wrong `payload` type annotation | Issue #12 (Type hinting incompleteness) — flagged *the file* but **wrong issue** | ⚠️ **Missed** |
| C7 | `data["choices"][0]...` KeyError | Issues #2 + #8 (No response validation) | ✅ |
| C8 | Function name doesn't match purpose | Not flagged | ❌ **Missed** |
| C9 | `# type: ignore` silence | Issue #17 hints at it | ⚠️ **Partial** |

**C-category recall:** 3 full + 3 partial / 9 = 5/9 hits (56%). **Mediocre on smells.**

### Category D — Missing Infrastructure (6 baseline)

| ID | Baseline issue | Mini-Agent finding | Match? |
|---|---|---|---|
| D1 | No tests | Issue #21 | ✅ |
| D2 | No README | Issue #20 | ✅ |
| D3 | No requirements.txt | Issue #19 | ✅ |
| D4 | No error handling in base.py | Issue #4 covers | ✅ |
| D5 | No retry logic | Not flagged | ❌ **Missed** |
| D6 | No rate limiting | Not flagged | ❌ **Missed** |

**D-category recall:** 4/6 hits (67%). **Got the obvious ones, missed the more subtle ones.**

### Category E — Architectural (3 baseline)

| ID | Baseline issue | Mini-Agent finding | Match? |
|---|---|---|---|
| E1 | Two competing implementations | Not flagged as architectural issue | ❌ **Missed** |
| E2 | **CRITICAL: LLM controls endpoint (architectural SSRF)** | Not flagged | ❌❌ **Missed (CRITICAL)** |

**E-category recall:** 0/3 hits (0%). **Architectural thinking was not done at all.**

---

## Aggregate Recall

| Category | Baseline count | Found (full) | Found (partial) | Missed | Recall |
|---|---|---|---|---|---|
| A — Bugs | 8 | 3 | 4 | 1 | 7/8 = 88% |
| B — Security | 4 | 1 | 1 | 2 | 2/4 = 50% |
| C — Smells | 9 | 3 | 2 | 4 | 5/9 = 56% |
| D — Missing infra | 6 | 4 | 0 | 2 | 4/6 = 67% |
| E — Architectural | 3 | 0 | 0 | 3 | 0/3 = 0% |
| **Total** | **30** | **11** | **7** | **12** | **18/30 = 60%** |

**Recall: 60% (threshold was ≥60% → BARE PASS on raw count)**

But: of those 18, 7 are partial (only caught the surface, not the actual bug). If we score partials as 0.5:
- Adjusted recall: (11 + 7×0.5) / 30 = 14.5/30 = **48.3%** → FAIL

**Of the 2 CRITICAL issues in the baseline, Mini-Agent found 0.** Both B4 (SSRF) and E2 (LLM controls endpoint) are architectural security issues that Mini-Agent did not surface at all.

## Precision — Did Mini-Agent hallucinate?

Mini-Agent reported 24 distinct findings. Going through them:

| # | Mini-Agent finding | Real? | Notes |
|---|---|---|---|
| 1 | Dead server instantiation | ✅ Real (A3) | |
| 2 | Unhandled response structure | ✅ Real (C7) | |
| 3 | Missing HTTP timeout | ✅ Real (A4) | |
| 4 | Generic exception swallowing | ✅ Real (A6) | |
| 5 | Duplicate server instantiation | ✅ Real (A3, duplicate of #1) | **DUPLICATE FINDING** |
| 6 | Hardcoded credentials/URL | ⚠️ Partial | Says "acceptable" — wrong framing |
| 7 | Silent error return | ✅ Real (A6 adjacent) | |
| 8 | Potential KeyError in model parsing | ✅ Real (C7 adjacent) | |
| 9 | Unreachable code (secret_dict) | ✅ Real (A1) | |
| 10 | String concat for Authorization | ✅ Real (A8 / B3) | |
| 11 | Inconsistent commented imports | ✅ Real (A2) | |
| 12 | Type hinting style "old union syntax" | ❌ **WRONG** | `Dict[str, str] | None` IS valid Python 3.10+ syntax. Not actually old. **HALLUCINATION** |
| 13 | No request validation | ⚠️ Subjective | Could be argued either way; not a bug, more of a hardening suggestion |
| 14 | Hardcoded HTTP-Referer | ✅ Real (B2) | |
| 15 | Magic numbers | ⚠️ Subjective | Real but minor — flagged `models[:50]` as magic number, which is defensible design |
| 16 | Missing module docstring | ✅ Real (low signal) | |
| 17 | Unused Type Variables | ✅ Real (A5/C9) | |
| 18 | Print for critical error | ✅ Real (C4) | |
| 19 | No requirements.txt | ✅ Real (D3) | |
| 20 | No README | ✅ Real (D2) | |
| 21 | No tests | ✅ Real (D1) | |
| 22 | No .env.example | ✅ Real, but **not in baseline** | **ADDITIONAL FINDING** (legitimate) |
| 23 | (dup of 1+5) | — | — |
| 24 | (dup of 1+5) | — | — |

**Counting:**
- Total findings: 24 (with at least 1 duplicate of #1)
- True positives (real issues): ~21
- **False positives / hallucinations:** 1 (#12 — "Dict is old syntax" is wrong)
- **Subjective / arguable:** ~2 (#13, #15)
- **Additional findings (not in baseline, but real):** 1 (#22 — `.env.example`)

**Precision: 21/24 = 87.5%** (or 22/24 = 91.7% if we count .env.example as bonus)

This passes the ≥70% precision threshold.

## Structure & Usability

✅ Report saved to `MINI_AGENT_REVIEW.md` as requested
✅ Severity grouping (Critical / High / Medium / Low / Infrastructure)
✅ File:line references for every finding
✅ Code snippets included
✅ Recommendations provided
✅ Summary table at the end
❌ Date in report says "2025-06-27" instead of 2026 — minor hallucination in metadata
✅ Categorized sections clear
❌ Findings #1 and #5 are literally duplicates — shows it didn't deduplicate its own list

**Structure grade:** A- (would be A if not for duplicate finding and wrong date)

---

## Final Scorecard

| Metric | Score | Threshold | Pass? |
|---|---|---|---|
| Raw recall | 60% | ≥60% | ✅ Bare pass |
| Adjusted recall (partials = 0.5) | 48% | — | ❌ Fail |
| Precision | 87.5% | ≥70% | ✅ Pass |
| Critical issue recall | 0/2 = 0% | — | ❌❌ **Major fail** |
| Structure & usability | A- | — | ✅ Pass |
| Hallucinations | 1 minor + 1 wrong-date | low | ⚠️ Acceptable |

---

## Verdict on Mini-Agent merits (interim, Phase 0–2 only)

### What Mini-Agent demonstrated works
1. **Harness is real** — installs via `uv tool install`, runs cleanly, exits cleanly
2. **API integration works** — MiniMax-M2.5 via api.minimaxi.com responded correctly
3. **ReAct loop is functional** — read file → think → write file → verify file exists → summarize
4. **Bash + file tools work** — used `ls` to verify its own write
5. **Token efficiency is good** — 6,732 tokens for a full code review is reasonable
6. **Speed** — 36 seconds wall clock for end-to-end review is fast
7. **Surface-level bug-finding is decent** — found 88% of bugs (A-category)
8. **Output format is structured** — produced usable Markdown report

### What Mini-Agent did NOT demonstrate
1. **Architectural thinking** — completely missed E1, E2 (two-competing-impls, LLM-controls-endpoint)
2. **Security depth** — missed B4 (SSRF), the actual critical issue
3. **Reasoning about caller-controlled inputs** — never considered what an LLM tool caller could do
4. **Connecting findings to root cause** — flagged A1 as "unreachable code" instead of "crash at import"
5. **Long-horizon tasks** — this was a single-step task; not tested

### What this tells us about M3 weakness compensation

The harness works mechanically. It does NOT compensate for M3's B-class reasoning weaknesses on architectural / security questions — exactly the class of weakness that the user hoped to mitigate. A more thoughtful reviewer (human or a stronger model) would have flagged the SSRF / endpoint-control issue immediately. M2.5 (which Mini-Agent is using by default) shows the same weakness we expected of M3 — it sees the surface, not the design.

### Should we proceed to Phase 3 (test-writing) and Phase 4 (end-to-end)?

**Yes, but with adjusted expectations.** The harness itself works. The interesting question now is whether it can sustain multi-step work (Phase 4) where it has to fix issues AND verify tests pass — that's where A-class tool-routing bugs would surface. Phases 3 and 4 will tell us if the harness has the legs to be a useful subagent runtime.

### Recommendation: don't change the plan structure
Phases 3 + 4 still answer the right question. If they fail, that's a clean signal that Mini-Agent's value is limited to short single-step tasks — exactly what the user's prior OpenViking pattern suggested was its strength.
