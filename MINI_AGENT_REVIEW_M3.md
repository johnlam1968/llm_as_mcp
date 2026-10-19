# Code Review Report — `base.py` and `mcp_server.py`

**Reviewer:** Mini-Agent (M3)
**Date:** Generated review session
**Scope:** `base.py`, `mcp_server.py`, and surrounding project infrastructure
**Files reviewed:**
- `/home/john/CodingProjects/llm_as_mcp/base.py` (67 lines)
- `/home/john/CodingProjects/llm_as_mcp/mcp_server.py` (91 lines)

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High     | 6 |
| Medium   | 9 |
| Low      | 8 |
| **Total**| **26** |

Both files expose MCP tools that proxy arbitrary LLM requests to remote APIs. They share a structurally identical decorator pattern but diverge in how they handle configuration. The codebase is small but exhibits multiple **critical security issues** (SSRF, no auth on a public API gateway, prompt-injection reflection) and **missing infrastructure** (no tests, no README, no dependency manifest, no packaging).

---

## Critical

### C1. Server-Side Request Forgery (SSRF) — `base.py:31, 51–52`  [FIXED]
The `base_url` parameter of `call_another_llm` is supplied by the MCP caller and passed verbatim to `httpx.AsyncClient().post(base_url, ...)`. Any MCP client (or any prompt-injected agent) can point this at internal addresses (`http://169.254.169.254/...`, `http://localhost:...`, `http://127.0.0.1:...`, `http://[::1]...`) to exfiltrate cloud metadata, hit internal services, or scan the internal network. There is **no allowlist** of hosts/schemes.

**Fix applied:** New `validate_base_url()` helper rejects non-`https` schemes, the `localhost` hostname, and any URL whose host is a literal IP falling in `127.0.0.0/8`, `169.254.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `::1/128`, `fc00::/7`, or `fe80::/10`. Called as the first line of `call_another_llm`, before any HTTP request. Covered by `tests/test_ssrf.py`.

### C2. Arbitrary, unauthenticated LLM API spend / proxy abuse — `base.py:31, 46–60`
Because (a) the `model` parameter selects a key from `secret_dict`, (b) the tool is exposed over MCP with no caller authentication, and (c) `secret_dict` holds provider keys in plaintext, any process that can reach this MCP server can burn API credits on arbitrary models. Combined with C1, this also allows probing which models are configured (oracle attack) by observing which key exists vs. raises.

### C3. Secrets loaded from env, no validation, fail-fast crash on import — `base.py:9–13`  [FIXED]
```python
secret_dict_env = os.environ.get("LLM_API_KEY_DICT")
secret_dict = json.loads(secret_dict_env) if secret_dict_env else None
if not secret_dict:
    print("⚠️  secret_dict not set. Please set it in your .env file.")
    sys.exit(1)
```
- Hard `sys.exit(1)` at module import time turns an optional-config issue into a non-recoverable process death. Any test, REPL session, or alternate entrypoint that imports this module dies immediately.
- `json.loads` of an environment string is fragile — typos or trailing whitespace (`LLM_API_KEY_DICT='{"k":"v"} '`) raise `JSONDecodeError` and crash the import with no actionable error message.
- No schema validation: `secret_dict` could be a list, int, or `{}` (which is falsy and crashes on line 11, but `{"k": ""}` would pass and silently yield empty API keys later).
- `print` of a warning to **stdout** is inappropriate for libraries; should be `logging.warning` to `stderr`.

**Fix applied:** `sys.exit(1)` removed; a missing or unparseable `secret_dict` now emits a `logger.warning(...)` and the module imports cleanly. `json.JSONDecodeError` is caught. The conftest.py in tests/ still sets `LLM_API_KEY_DICT` before import.

---

## High

### H1. Prompt injection through `persona` and `query` is unmitigated — `base.py:31, 56–57`; `mcp_server.py:28, 51–52`
The `persona` string is sent as a system message. Since the surrounding MCP client is itself an LLM, the **upstream** LLM that reads this tool's output may treat returned content as instructions. There is no:
- Length cap on `persona`/`query` (denial-of-wallet via token-bombing).
- Stripping of embedded `<<SYSTEM>>` style markers.
- Disclaimer prefix in tool output warning downstream agents that the response is untrusted.
- Sanitization of control characters / null bytes in the response before returning it (`mcp_server.py:62`, `base.py:63`).

### H2. `data["choices"][0]["message"]["content"]` assumes a fixed schema — `base.py:63`; `mcp_server.py:62`
Both files blindly index into the OpenAI-style response without checking that `choices` exists, is non-empty, or contains the expected keys. A 200 OK with an empty list, a moderation-blocked response, or a non-OpenAI-shape response raises `KeyError` / `IndexError`, which surfaces to the MCP caller as an opaque tool error. Should be a guarded extraction with a clear error message.

### H3. No `response.raise_for_status()` on `base.py` — `base.py:50–63`
Unlike `mcp_server.py:60`, `base.py` does not call `response.raise_for_status()`. HTTP 4xx/5xx responses with valid JSON bodies (or with the error in the body but the body still returning a `choices` key by accident) are silently treated as success. A 401 with `{"choices": [...]}` from a misconfigured upstream would not be detected.

### H4. No `timeout` on the outbound `httpx.AsyncClient` in `base.py` — `base.py:50–51`  [FIXED]
`async with httpx.AsyncClient() as client:` is constructed with the default timeout (5s connect / 5s read in httpx, but unbounded in some async configurations — verify). A hung upstream will block the MCP worker indefinitely, exhausting concurrency and stalling the agent. `mcp_server.py:59, 76` correctly uses `timeout=60.0` / `timeout=30.0`.

**Fix applied:** `httpx.AsyncClient()` in `call_another_llm` is now constructed with `timeout=30.0`. Covered by `tests/test_ssrf.py::test_call_another_llm_uses_30_second_timeout`.

### H5. `mcp_tool` decorator: type-ignore hides a real typing bug — `base.py:28`; `mcp_server.py:24`
```python
return server.tool(structured_output=False)(func)  # type: ignore
```
The `# type: ignore` suppresses a genuine issue: `FastMCP.tool` returns a decorator whose return type may not be `F`. More importantly, when `structured_output=False` is applied, the return type expected from the tool function is `str` (or unstructured content). The decorator binds `F = TypeVar('F', bound=Callable[..., Awaitable[str]])`, but the decorator itself is not generic — it always returns the same decorator closure regardless of `F`. This silently breaks the moment someone adds a tool that doesn't return `str`. Use a `ParamSpec` / proper generic decorator.

### H6. No connection pooling / no reuse — `base.py:50`; `mcp_server.py:57, 74`
Both files create a fresh `httpx.AsyncClient()` per tool invocation. This means new TLS handshakes, new connection pools, no keep-alive, and no shared `Limits()` configuration. For an MCP server that may receive many concurrent calls, this is wasteful and slow. Lift the client to module scope (or to the server lifespan).

---

## Medium

### M1. Duplicate `FastMCP` instantiation in `base.py` — `base.py:15, 23`  [FIXED]
```python
server=FastMCP("name of server")  # line 15
...
server = FastMCP("llm_through_mcp")  # line 23
```
The first `FastMCP("name of server")` is immediately overwritten by the second. This is dead code that misleads readers and suggests the author intended two servers. Delete line 15.

**Fix applied:** Dead `server=FastMCP("name of server")` line removed; only the `server = FastMCP("llm_through_mcp")` instantiation remains.

### M2. Imports scattered mid-module — `base.py:1–7, 18`; `mcp_server.py:1–6, 14`
`from typing import Callable, TypeVar, Awaitable` is imported on line 18 of `base.py` (and line 14 of `mcp_server.py`), well after the `from typing import Dict` import on line 7. PEP 8 requires all imports at the top of the file. Also, the commented-out `from fastmcp import FastMCP` on `base.py:1` / `mcp_server.py:3` should be deleted rather than left as historical clutter.

### M3. `json.loads` of env without try/except — `base.py:10`
As noted in C3 — also worth flagging here as a code-smell: environment variables should be parsed defensively. Wrap in `try/except (json.JSONDecodeError, TypeError)` and produce a clear error.

### M4. Bearer token built via string concatenation — `base.py:60`
```python
headers={"Authorization": "Bearer " + api_key}
```
Not a vulnerability (httpx handles the value safely), but inconsistent with `mcp_server.py:41` which uses an f-string. Pick one style.

### M5. Generic `except Exception as e` swallows real failures — `mcp_server.py:63–64, 87–88`  [FIXED]
Returning `f"Agent Error: {str(e)}"` to the MCP caller hides stack traces from logs and conflates network errors, JSON parse errors, and HTTP errors. At minimum, log the exception with `logging.exception(...)` and re-raise non-network exceptions. Returning the raw error string also leaks upstream implementation details to the calling agent.

**Fix applied:** Both `call_llm` and `list_available_models` now split their exception handling into three specific branches — `httpx.HTTPError`, `json.JSONDecodeError`, and `(KeyError, IndexError, TypeError)` — and call `logger.exception(...)` before returning the user-facing error string.

### M6. `list_available_models` truncates silently and exposes nothing about pricing/limits — `mcp_server.py:67–88`
- `models[:50]` silently drops the rest with no "and N more" indicator. The LLM calling this tool may not realize the list is truncated and could pick a non-existent model ID.
- The function description in the docstring mentions "pricing, and context limits" but the formatted output (`mcp_server.py:84`) only emits `id`, `name`, `context_length`. Misleading documentation.
- No cache: every call re-hits OpenRouter. Consider caching for `ttl=3600`.

### M7. Hardcoded `HTTP-Referer` localhost URL — `mcp_server.py:42`
```python
"HTTP-Referer": "http://localhost:3000",
```
OpenRouter uses this for ranking/attribution. Shipping a hardcoded `localhost` referer in a distributable server is wrong — it should be the operator's actual domain or be configurable via env var.

### M8. `call_llm` returns a string error instead of raising — `mcp_server.py:37–38, 63–64`
Returning `"Error: OPENROUTER_API_KEY not found..."` from a function whose return type is annotated `-> str` blurs the contract — the caller cannot distinguish "the LLM said X" from "the tool failed". MCP supports structured error responses; raise an exception or return a structured error object.

### M9. Mutable module-level global state — `base.py:9–10`; `mcp_server.py:10, 19`
`secret_dict`, `OPENROUTER_KEY`, `server` are all module globals mutated at import time. This makes the module:
- Untestable (can't inject test fixtures without monkeypatching).
- Unsafe to import from multiple contexts (e.g., a test runner and an app).
- Sensitive to import-order side effects (C3).

Move configuration into a factory / context and inject the client.

---

## Low

### L1. Inconsistent string-quote style — both files
Single quotes are used for `'system'`, `'user'` keys, but double quotes elsewhere. Pick one (PEP 8 prefers double quotes, but consistency matters more).

### L2. Trailing whitespace / line-length inconsistencies
Several lines exceed 100 chars (e.g., `base.py:31` is ~120 chars). Add a `ruff` / `black` config.

### L3. Docstring param order does not match signature order — `mcp_server.py:29–36`
Signature is `(persona, query, model, temperature)`; the Args section is `(query, temperature, model, persona)`. Sphinx/IDE tooling that pulls args by position can misalign help text.

### L4. Magic number `50` for model list truncation — `mcp_server.py:83`
Lift to a named constant (`MAX_MODELS_RETURNED = 50`) so it can be tuned.

### L5. `# Required by OpenRouter` comment is now stale — `mcp_server.py:42`
OpenRouter has loosened the referer requirement; this comment claims a stronger constraint than exists. Update or remove.

### L6. Type alias `payload` uses string union with `dict[str, str]` — `mcp_server.py:48`
`dict[str, str | list[dict[str, str]] | float]` is correct but verbose and not re-used. Consider `TypedDict` or `TypedDict` per role.

### L7. No `__all__` defined in either module — both files
Defining `__all__ = ["mcp_tool", "call_llm", "list_available_models"]` (and for `base.py`: `["mcp_tool", "call_another_llm"]`) clarifies the public surface.

### L8. `name of server` placeholder was caught (M1) but also: the MCP server name should be configurable — `base.py:23`, `mcp_server.py:19`
Both files hardcode `"llm_through_mcp"`. If two instances run side-by-side (dev + prod), they collide in MCP discovery. Accept via env var.

---

## Missing Infrastructure

The following files/configs are **absent** from the repository root (`/home/john/CodingProjects/llm_as_mcp/`) and should be added:

| Item | Purpose | Severity (infrastructure) |
|------|---------|---------------------------|
| `README.md` | Explain what the project does, how to configure `.env`, how to run, MCP client setup | Critical |
| `requirements.txt` / `pyproject.toml` | Pin `mcp`, `httpx`, `python-dotenv`, `fastmcp` versions | Critical |
| `tests/` directory with `test_base.py` / `test_mcp_server.py` | No test coverage of any kind; decorator, error paths, and HTTP behavior are untested | Critical |
| `.env.example` | Template for `OPENROUTER_API_KEY` and `LLM_API_KEY_DICT` so users know the schema | High |
| `pyproject.toml` with `[tool.ruff]` / `[tool.black]` / `[tool.mypy]` | Enforce style and types (the `# type: ignore` on the decorator hides real issues) | Medium |
| `LICENSE` | No license declared | High (legal) |
| `CONTRIBUTING.md` / issue templates | Optional but standard for any public repo | Low |
| CI config (`.github/workflows/ci.yml`) | No automated checks; given no tests exist, this is the only safety net | High |
| `.dockerignore` / `Dockerfile` | Optional but useful for an MCP server that may be containerized | Low |
| `CHANGELOG.md` | No history of changes | Low |

### Specific test gaps

At minimum, the following should be covered:

1. `mcp_tool` decorator preserves the wrapped function's metadata (`__name__`, `__doc__`, `__wrapped__`).
2. `call_llm` with a mocked `httpx.AsyncClient`:
   - success path returns content
   - 401 raises / returns a structured error
   - empty `choices` list returns a clear message
   - missing API key returns a clear message
3. `list_available_models` formats output correctly and truncates with a "more available" indicator.
4. `call_another_llm` (base.py):
   - rejects non-http(s) schemes
   - rejects loopback / link-local hosts (mitigates C1)
   - raises when model not in `secret_dict`
   - raises when `secret_dict` is empty
5. Integration test using `pytest-httpx` or `respx` to assert headers, payload shape, timeout.

---

## Recommendations (priority order)

1. **Fix C1 immediately**: add a host allowlist (and scheme allowlist — `https://` only) to `base.py:51–52`. Reject `localhost`, `127.0.0.0/8`, `169.254.0.0/16`, `::1`, `fc00::/7`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, and IPv6 link-local.
2. **Fix C3**: replace `sys.exit(1)` with `raise RuntimeError(...)` from a `main()` / `__main__` guard; validate `secret_dict` schema.
3. **Add `requirements.txt`** with pinned versions: `mcp>=0.1.0`, `httpx>=0.27`, `python-dotenv>=1.0`, (optionally) `fastmcp>=0.1.0`.
4. **Add `README.md`** with setup, `.env` schema, and run instructions.
5. **Add a `tests/` directory** with at least the unit tests listed above; install `pytest`, `pytest-asyncio`, `respx` (or `pytest-httpx`).
6. **Lift `httpx.AsyncClient` to module scope** with a configured `timeout`, `limits`, and `follow_redirects=False` (also helps C1).
7. **Remove the duplicated `FastMCP(...)` instantiation** on `base.py:15` (M1) and consolidate imports (M2).
8. **Replace generic `except Exception`** with `httpx.HTTPError`, `json.JSONDecodeError`, `KeyError` and log via `logging.exception` (M5).
9. **Add type checking** (`mypy --strict` or `pyright`) — the `# type: ignore` on the decorator masks a real generic-typing problem (H5).
10. **Add `.env.example`** showing both `OPENROUTER_API_KEY=<key>` and `LLM_API_KEY_DICT={"openai/gpt-4o":"sk-...","anthropic/claude-3.5-sonnet":"sk-ant-..."}`.

---

## Files Reviewed (not modified)

- `/home/john/CodingProjects/llm_as_mcp/base.py` — reviewed only.
- `/home/john/CodingProjects/llm_as_mcp/mcp_server.py` — reviewed only.
- `.env`, `.gitignore` — inspected for context only.