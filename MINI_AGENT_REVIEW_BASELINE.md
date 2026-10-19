# Phase 0 Baseline — `llm_as_mcp` Review Rubric

**Author:** Hermes (independently, before running Mini-Agent)
**Date:** 2026-06-27
**Files reviewed:** `base.py` (66 LOC), `mcp_server.py` (90 LOC)
**Scoring key:** Mini-Agent Phase 2 will be scored against this list. Recall = % of these issues Mini-Agent finds. Precision = (correctly flagged issues) / (all issues Mini-Agent flags).

---

## Category A — Bugs / Correctness

| ID | Location | Issue | Severity |
|---|---|---|---|
| A1 | `base.py:8-11` | `sys.exit(1)` at **module import time** if `LLM_API_KEY_DICT` env var is unset. Crashes the entire server on missing config. Should fail inside `call_another_llm` instead. | High |
| A2 | `base.py:5` | `from mcp.server.fastmcp import FastMCP` is the canonical import, but line 2 also has a commented-out `from fastmcp import FastMCP`. Dead/conflicting comment. | Low |
| A3 | `base.py:14, 19` | `FastMCP("name of server")` and `FastMCP("llm_through_mcp")` — **two server instantiations in the same file**, with different names. The first one (`server=FastMCP(...)`) is then overwritten by line 19 (`server = FastMCP(...)`). The first one is dead code. | High |
| A4 | `base.py:48` | `httpx.AsyncClient()` used **without timeout** — a hung server means the tool call hangs forever. Compare `mcp_server.py:72` which has `timeout=60.0`. | High |
| A5 | `base.py:30-32` | `mcp_tool` decorator wraps `server.tool(...)` but uses a `TypeVar('F', bound=Callable[..., Awaitable[str]])`. The actual function `call_another_llm` returns `str`, not `Awaitable[str]`. The decorator type hint is wrong (the function is sync-looking but the tool must be async because FastMCP needs `Awaitable`). The function IS async so this works at runtime, but the type annotation is misleading. | Low |
| A6 | `mcp_server.py:75-83` | `try/except Exception` swallows ALL errors and returns them as a string to the LLM. The LLM has no way to distinguish a network timeout from a 401 from a malformed response from a `KeyError` on `data["choices"]`. | Medium |
| A7 | `mcp_server.py:76` | `response.raise_for_status()` raises an `httpx.HTTPStatusError`, caught by the bare `except Exception`, but the error message returned to the LLM leaks internal details (full exception string). | Low |
| A8 | `base.py:53` | `Authorization: Bearer ` followed by `+ api_key` — if `api_key` is empty, this sends `"Bearer "` with trailing space, which the server may reject unpredictably. No defensive check. | Low |

## Category B — Security

| ID | Location | Issue | Severity |
|---|---|---|---|
| B1 | `base.py:8-11` | `LLM_API_KEY_DICT` parsed from env var with no validation. If env var is a malformed JSON string, `json.loads` raises and the server crashes at import. | Medium |
| B2 | `mcp_server.py:64` | `Authorization: Bearer {OPENROUTER_KEY}` with `HTTP-Referer: http://localhost:3000` hardcoded. The referer should be configurable — some models / gateways validate it. | Low |
| B3 | `base.py:50-51` | `Authorization: Bearer " + api_key` — string concat, no URL-encoding. If `api_key` ever contained special chars (unlikely but possible) it would be malformed. | Low |
| B4 | `base.py:50` | The HTTP request sends `base_url` as a **POST URL** with no scheme/host validation. A malicious caller (LLM) could point this at `http://169.254.169.254/...` (AWS metadata service) or `file://...` — it's a server-side request forgery (SSRF) vector. The `base_url` parameter comes from the LLM tool caller. | **Critical** |

## Category C — Code Smells / Maintainability

| ID | Location | Issue | Severity |
|---|---|---|---|
| C1 | Both files | The `mcp_tool` decorator, the `TypeVar` declaration, the `server = FastMCP("llm_through_mcp")` line, and the `mcp_tool` import block are **duplicated verbatim** across `base.py` and `mcp_server.py`. | High |
| C2 | `base.py:14` | Server name `"name of server"` — placeholder text never updated. Embarrassing. | Low |
| C3 | `mcp_server.py:14` | `OPENROUTER_KEY = os.getenv(...)` at module level — same pattern as A1, crashes at import if missing. | Medium |
| C4 | `base.py:8` | Module-level `print("⚠️ ...")` + `sys.exit(1)` — not using `logging` module, so the warning is lost when the server runs detached. | Low |
| C5 | Both files | No `if __name__ == "__main__":` guard around the tool definitions (well, `base.py:62` and `mcp_server.py:88` have one for `server.run()` but the tool registration happens at import time regardless). Tool registration as a side effect of import is a known FastMCP footgun. | Low |
| C6 | `mcp_server.py:30-35` | `payload` type annotation uses a Union `dict[str, str | list[dict[str, str]] | float]` — but `messages` is a list of dicts that also contain `content` (str) and `role` (str). The annotation is structurally wrong (Pyright/mypy would flag). | Low |
| C7 | `mcp_server.py:82-83` | `data["choices"][0]["message"]["content"]` — five levels of nested-dict access with no `KeyError` handling. If the API returns a different shape (e.g. error response with `error` key instead of `choices`), this crashes. | Medium |
| C8 | `base.py:41-47` | Docstring describes `base_url` as a parameter but the function name is `call_another_llm` — the user has no way to know from the function name what kind of "another LLM" is being called. | Low |
| C9 | `mcp_server.py:21` | `mcp_tool` decorator: `# type: ignore` comment silences the type checker. This means the decorator IS lying to the type checker about its return type. The function being decorated is `async def`, which returns `Awaitable[str]`, but the `TypeVar` bound is `Callable[..., Awaitable[str]]` which doesn't match the actual signature. | Low |

## Category D — Missing Infrastructure

| ID | Issue | Severity |
|---|---|---|
| D1 | **No tests at all** — no `test_*.py` files, no `pytest` config, no `conftest.py`. | High |
| D2 | No `README.md` — neither file documents how to install, configure, or run. | Medium |
| D3 | No `requirements.txt` or `pyproject.toml` — dependencies (`mcp`, `httpx`, `python-dotenv`) are undocumented. | Medium |
| D4 | No error handling for the `httpx` requests beyond the bare `except Exception` in `mcp_server.py`. `base.py` has zero error handling. | High |
| D5 | No retry logic for transient failures (5xx, network blips). | Medium |
| D6 | No rate limiting / cost controls — an LLM tool caller could fire this 1000x/min and burn API credits. | Medium |

## Category E — Architectural

| ID | Issue | Severity |
|---|---|---|
| E1 | `base.py` and `mcp_server.py` look like **two competing implementations of the same idea** (call another LLM via MCP). One uses `OPENROUTER_KEY` + hardcoded URL, the other uses `LLM_API_KEY_DICT` env var + caller-supplied URL. Why both? The audit (`CODING_PROJECTS_AUDIT_2026-06-04.md`) suggested merging into `llm_public`. | High |
| E2 | `call_another_llm` accepts arbitrary `base_url` from the LLM tool caller (see B4) — this is an **architectural anti-pattern**. The LLM should not be able to choose which API endpoint to hit; it should choose which model/persona. | **Critical** |

---

## Summary checklist for Mini-Agent scoring

- **Total issues catalogued:** 30 (8 bugs, 4 security, 9 smells, 6 missing-infra, 3 architectural)
- **Critical issues:** 2 (B4 SSRF, E2 LLM controls endpoint)
- **High issues:** 7
- **Medium issues:** 9
- **Low issues:** 12

### Scoring rubric

- **Recall ≥ 60%** = Mini-Agent found 18+ issues → pass
- **Precision ≥ 70%** = at most ~8 false positives across Mini-Agent's full report
- **Bonus** for finding B4/E2 (critical issues I might have missed)
- **Penalty** for hallucinating issues that aren't real (false precision)
- **Structure bonus** if output is sorted by severity/category rather than flat list
