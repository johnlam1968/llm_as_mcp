# Code Review: `base.py` and `mcp_server.py`

**Reviewer:** Hermes Agent (independent review)
**Files reviewed:** `base.py` (66 LOC), `mcp_server.py` (90 LOC)
**Total project size:** ~156 LOC
**Scope:** Two MCP-server entrypoints that wrap calls to external LLM APIs (one generic, one OpenRouter-specific).

---

## Summary

Both files appear to be near-duplicate MCP servers. `mcp_server.py` is the more complete of the two (timeout, error wrapping, OpenRouter headers); `base.py` is a more generic variant that reads API keys per-model from a JSON-encoded env var. Each file independently redeclares the same `mcp_tool` decorator and instantiates its own `FastMCP` server, so importing both in the same process would silently overwrite the first server. Beyond the duplication, the code has several real bugs (no HTTP status check, no JSON decode guard, SSRF-prone parameter, no retry on transient errors) and is missing standard project infrastructure (tests, README, dependency manifest, logging, requirements pinning).

---

## Critical

### C1. `base.py:11-13` — Module-level `sys.exit(1)` on import

```python
if not secret_dict:
    print("⚠️  secret_dict not set. Please set it in your .env file.")
    sys.exit(1)
```

**Why it's a problem:** This runs at *import time*, not at server startup. Any test, REPL session, or sibling module that imports `base.py` (e.g. for `mcp_tool`, `server`, or `call_another_llm`) will terminate the entire process with no exception and no stack trace the caller can catch. `sys.exit` inside a library module is an anti-pattern; it makes the file unimportable in any context where the env var isn't set, even for read-only inspection or static analysis. It also silently masks the failure with a bare `print` instead of logging.

**Recommendation:** Move the validation into the tool function itself (raise a clear exception) or into a `main()` / `run()` entrypoint. Never call `sys.exit` at import time.

---

### C2. `base.py:31` — `base_url` is an MCP-tool parameter (SSRF + auth-leak vector)

```python
async def call_another_llm(persona: str, query: str, model: str, temperature: float, base_url: str) -> str:
```

**Why it's a problem:** `base_url` is exposed as a tool parameter, so any caller of the MCP server (which by design is an LLM) can direct the server to POST to *any* URL on the internet — including `http://169.254.169.254/...` (cloud metadata), `http://localhost:6379` (Redis), internal admin endpoints, etc. — while sending the API key in the `Authorization` header. This is a textbook server-side request forgery (SSRF) plus a credential-exfiltration vector: the LLM caller controls the destination, and the server attaches a Bearer token it controls.

**Recommendation:** Do not expose `base_url` as a parameter. Resolve it server-side from a hard-coded or allow-listed map keyed on `model` (e.g. `BASE_URLS = {"openrouter": "https://openrouter.ai/api/v1/chat/completions", ...}`). At minimum, validate the URL against an allow-list and reject non-HTTPS, internal IPs, and loopback.

---

### C3. `base.py:50-61` — No `raise_for_status()` and no HTTP-error handling

```python
async with httpx.AsyncClient() as client:
    response = await client.post(
        base_url,
        json={...},
        headers={"Authorization": "Bearer " + api_key}
    )
data = response.json()
return data["choices"][0]["message"]["content"]
```

**Why it's a problem:** The code never calls `response.raise_for_status()`. If the upstream API returns 401/403/429/500, the code blindly calls `response.json()`, which either succeeds with an error payload (and then crashes on `data["choices"]` with a `KeyError`/`IndexError`) or raises a `JSONDecodeError`. Either way the MCP caller receives an opaque traceback instead of a useful error, and the API key is effectively wasted on each failed call because there is no retry/backoff (see H3). This is the single most likely production failure mode.

**Recommendation:** Add `response.raise_for_status()` before parsing, and wrap the network + parse + shape-access in `try/except` blocks that return structured errors (or re-raise with context). `mcp_server.py` does call `raise_for_status()` — that pattern should be back-ported here.

---

## High

### H1. `base.py:15` and `base.py:23` — `server` is instantiated twice; the first instance is silently discarded

```python
server=FastMCP("name of server")
...
server = FastMCP("llm_through_mcp")
```

**Why it's a problem:** The first `FastMCP("name of server")` is created and immediately replaced on line 23. The dead first instance has already registered nothing, but the duplicate assignment is confusing and signals copy-paste debt. More importantly, this is the exact same pattern as `mcp_server.py:19`, which means importing both modules in the same process (e.g. for shared utilities) silently overwrites whichever was imported first — and whichever `@mcp_tool`-decorated function ran first wins. There is no warning, no error, and no easy way to detect the bug.

**Recommendation:** Pick one server instance per file, give it a meaningful name, and extract the shared `mcp_tool` decorator into a single helper module (e.g. `mcp_common.py`) imported by both files.

---

### H2. `base.py:10` — `json.loads` on env var without error handling

```python
secret_dict: Dict[str, str] | None = json.loads(secret_dict_env) if secret_dict_env else None
```

**Why it's a problem:** If `LLM_API_KEY_DICT` is set to a non-empty but malformed string (a stray quote, trailing comma, anything), `json.loads` raises `JSONDecodeError` at import time, which — combined with C1's module-level exit — produces an unhelpful traceback and kills the server before any tool can run. A typo in `.env` becomes a production outage rather than a clear error.

**Recommendation:** Wrap in `try/except json.JSONDecodeError`, raise a clear error message indicating the env var name and that it must be valid JSON, and validate the parsed shape (must be `dict[str, str]`).

---

### H3. Both files — No retry / backoff for transient API failures

```python
# base.py:50-61
async with httpx.AsyncClient() as client:
    response = await client.post(base_url, json=..., headers=...)
```

**Why it's a problem:** LLM APIs routinely return 429 (rate limit), 502/503/504 (upstream transient), or briefly time out. Without retries, every transient blip surfaces to the MCP caller as a hard error. Without exponential backoff, a retry (if added later) risks amplifying the outage. There is also no jitter, so multiple concurrent callers would re-burst in lockstep.

**Recommendation:** Use `httpx.AsyncClient` with a transport that supports retries (`httpx-retries` or wrap calls in a small retry helper), or use `tenacity` with exponential backoff + jitter, retrying only on 429/5xx and `httpx.TransportError`. Cap retries (e.g. 3) and surface a clear final error.

---

### H4. `mcp_server.py:37-38` and `mcp_server.py:63-64` — Errors returned as strings instead of raised

```python
if not OPENROUTER_KEY:
    return "Error: OPENROUTER_API_KEY not found in environment."
...
except Exception as e:
    return f"Agent Error: {str(e)}"
```

**Why it's a problem:** Two distinct issues compound here:

1. The missing-key case returns a successful `str` result, so the MCP caller (an LLM) receives the literal text "Error: OPENROUTER_API_KEY not found..." and may try to interpret it as a real answer.
2. The bare `except Exception as e` swallows everything — timeouts, JSON decode errors, schema changes — and returns them as a string, again indistinguishable from a successful LLM response. There is no logging, so operators have no visibility into failures.

The same anti-pattern in `base.py:43-44` is *better* (it raises `ValueError`) but the message is still swallowed at the MCP boundary in some clients.

**Recommendation:** Log the exception (see M1) and raise a typed exception (`McpError`, `RuntimeError`) instead of returning a string. Configure the MCP server's error handler to surface these to the client as errors, not as tool results.

---

### H5. `base.py:46-48` and `mcp_server.py:10` — API key / Bearer header can be malformed if env is empty

```python
# base.py
api_key = secret_dict.get(model)
if not api_key:
    raise ValueError(f"API key for model {model} not found in secret_dict.")
...
headers={"Authorization": "Bearer " + api_key}

# mcp_server.py
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
...
"Authorization": f"Bearer {OPENROUTER_KEY}",
```

**Why it's a problem:** In `base.py` the empty-key check is done, *but* a non-empty whitespace string (e.g. `" "`) passes `if not api_key` and produces `Authorization: Bearer  ` (two spaces, no token), which most APIs reject with 401 — a confusing failure mode for the operator who only sees "auth failed". In `mcp_server.py`, the only check is the bare `if not OPENROUTER_KEY` later, but if it ever *is* set to whitespace, the same malformed header is produced and sent on every call.

**Recommendation:** Validate the key explicitly: `if not api_key or not api_key.strip(): raise ...`. Strip whitespace before constructing the header. Apply the same check in both files.

---

## Medium

### M1. Both files — Zero logging

```python
# No `import logging`, no `logger = logging.getLogger(__name__)` anywhere.
# base.py:12 — uses print()
# mcp_server.py — no logging at all
```

**Why it's a problem:** When something goes wrong in production (and it will — see H3, C3), there is no record of what request was sent, what the upstream returned, or even that the tool was invoked. `print()` in `base.py` writes to stdout which the MCP host may or may not capture. Operators debugging a 3am outage have nothing to look at.

**Recommendation:** Add `logger = logging.getLogger(__name__)` at the top of each file, and log at INFO for tool invocations (model, base_url, latency) and ERROR/EXCEPTION for failures. Never log the API key itself.

---

### M2. `base.py:9-10` and `mcp_server.py:8` — Environment loading has side effects at import time

```python
# base.py
secret_dict_env = os.environ.get("LLM_API_KEY_DICT")
secret_dict: Dict[str, str] | None = json.loads(secret_dict_env) if secret_dict_env else None

# mcp_server.py
load_dotenv()
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
```

**Why it's a problem:** Both files read and parse env vars as a side effect of being imported. This makes them hard to test (you can't import the module without first setting env vars) and tightly couples the module to a specific runtime configuration. `load_dotenv()` in `mcp_server.py` additionally silently mutates `os.environ`, which is a global side effect any importer inherits.

**Recommendation:** Defer env reads into a `get_settings()` helper (or use `pydantic-settings` / `dynaconf`) and call it lazily inside the tool function. Tests can then patch the helper. Drop `load_dotenv()` from the module top-level — call it explicitly in `__main__` or a config entrypoint.

---

### M3. `base.py:26-28` and `mcp_server.py:22-24` — Duplicate decorator + `# type: ignore` masks a real typing problem

```python
def mcp_tool(func: F) -> F:
    """Custom decorator for MCP tools that automatically sets structured_output=False"""
    return server.tool(structured_output=False)(func)  # type: ignore
```

**Why it's a problem:** The `# type: ignore` comment is hiding the fact that `server.tool(...)` likely does not return a callable with the same signature as `func`. The decorator claims `Callable[..., Awaitable[str]]` but `server.tool()` may return something else, so the type system is being lied to. Worse, this decorator is *byte-for-byte duplicated* across both files, which means any fix has to be applied in two places.

**Recommendation:** Extract the decorator (and the `server` instance, ideally) into a shared module. Replace the `# type: ignore` with the correct return type, or use `cast(F, server.tool(...)(func))` if the runtime contract is what you want.

---

### M4. `base.py:31` — `temperature` parameter has no validation

```python
async def call_another_llm(persona: str, query: str, model: str, temperature: float, base_url: str) -> str:
```

**Why it's a problem:** `temperature` is passed straight to the upstream API. Most providers reject values outside `[0.0, 2.0]` with a 400, but some accept `NaN`, `inf`, or negative values and return nonsense. Because this is exposed to an LLM caller, a malformed temperature produces a wasted call and a confusing error.

**Recommendation:** Clamp/validate: `if not 0.0 <= temperature <= 2.0: raise ValueError(...)`.

---

### M5. Both files — No timeout on `httpx` calls in `base.py`; inconsistent in `mcp_server.py`

```python
# base.py:50 — no timeout argument at all
response = await client.post(base_url, json=..., headers=...)

# mcp_server.py:59 — 60s timeout (good)
response = await client.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60.0)
```

**Why it's a problem:** `httpx` defaults to a 5-second timeout on *each socket operation* but not on the total request, and many LLM calls (long generations, large context) routinely exceed 5s, so `base.py` will hang up partway through and surface a `TimeoutException` mid-generation. Worse, because there's no timeout *and* no error handling, a hung request can also exhaust the MCP server's connection pool.

**Recommendation:** Add an explicit `timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)` (or similar) to every request. `mcp_server.py` has 60s total which is on the low side for slow models — consider 120s.

---

### M6. `mcp_server.py:83` — Hard-coded slice `[:50]` with a "save context" comment

```python
for m in models[:50]: # Limit to top 50 to save context space
    summary.append(f"- ID: {m['id']} | Name: {m['name']} | Context: {m['context_length']}")
```

**Why it's a problem:** The number 50 is magic, undocumented as a constant, and silently drops models 51+. If the caller asked for a specific model (e.g. via a parameter) and it isn't in the top 50, the call returns success but the model isn't actually listed — the LLM caller will conclude the model doesn't exist. Also `m['id']`, `m['name']`, `m['context_length']` will `KeyError` if the upstream shape changes.

**Recommendation:** Make the limit configurable (default 50, override via tool parameter), and use `.get(...)` with a fallback for each field. Better: filter or sort to put the requested model first.

---

### M7. `base.py:43-44` and `base.py:47-48` — Duplicate key-presence check

```python
if not secret_dict:
    raise ValueError("secret_dict is not set.")
api_key = secret_dict.get(model)
if not api_key:
    raise ValueError(f"API key for model {model} not found in secret_dict.")
```

**Why it's a problem:** The first check is structurally impossible given C1 — `base.py` already `sys.exit(1)`s if `secret_dict` is falsy at import time, so this check at runtime can never fire. It's dead code that suggests the author didn't fully think through the control flow after adding the early exit.

**Recommendation:** Remove the dead check, or (better) fix C1 by removing the early exit and relying on the runtime check.

---

## Low

### L1. `base.py:1-7` — Imports scattered across the top of the file

```python
# from fastmcp import FastMCP
from mcp.server.fastmcp import FastMCP
import httpx
import sys
import os
import json
from typing import Dict
...
# Create a custom decorator that wraps @server.tool with structured_output=False
from typing import Callable, TypeVar, Awaitable
```

**Why it's a problem:** A commented-out import, then `from typing import Dict`, then 12 lines later another `from typing import ...` block. `sys` is imported solely for the anti-pattern in C1. PEP 8 / isort will flag this.

**Recommendation:** Consolidate all imports at the top in standard order (stdlib, third-party, local). Remove the commented-out `fastmcp` import (it's in version control — git remembers).

---

### L2. `mcp_server.py:1` — Unused `import os`

```python
import os
import httpx
```

**Why it's a problem:** `os` is only used for `os.getenv`, which works but is verbose; `os.environ` is also touched implicitly via `load_dotenv`. Not strictly a bug, but together with L1 suggests sloppy housekeeping.

**Recommendation:** Replace `os.getenv(...)` with `os.environ.get(...)` for consistency, or move env access into a helper (see M2) and drop the import from this module.

---

### L3. `base.py:15` — Server name `"name of server"` is a placeholder

```python
server=FastMCP("name of server")
```

**Why it's a problem:** This is dead code (overwritten on line 23), but if H1 is fixed and only one instance survives, the placeholder string is what users will see in their MCP client. It also makes log/trace correlation harder.

**Recommendation:** Pick a real name (matching the file, e.g. `"llm_generic"`) and remove the second instantiation.

---

### L4. Both files — `# type: ignore` without a justifying comment

```python
return server.tool(structured_output=False)(func)  # type: ignore
```

**Why it's a problem:** Per PEP 484 / mypy guidance, every `# type: ignore` should have an explanatory comment (e.g. `# type: ignore[return-value]  # FastMCP.tool returns a decorator`). Without it, future maintainers can't tell whether the suppression is safe to remove.

**Recommendation:** Add the specific error code and a one-line reason, or fix the type properly (see M3).

---

### L5. `mcp_server.py:42-44` — Hard-coded `HTTP-Referer` claims `localhost:3000`

```python
"HTTP-Referer": "http://localhost:3000", # Required by OpenRouter
"X-Title": "MCP Multi-Agent Hub",
```

**Why it's a problem:** OpenRouter uses `HTTP-Referer` for analytics and ranking; claiming `localhost:3000` is misleading and would be wrong in any non-localhost deployment. If this server is ever deployed, the referer should be the actual deployment URL (from an env var), not a hard-coded localhost.

**Recommendation:** Read the referer from an env var with a localhost default for dev, e.g. `os.getenv("APP_URL", "http://localhost:3000")`.

---

### L6. `mcp_server.py:66-67` — `list_available_models` returns a long string for LLM consumption but no test exists

```python
@mcp_tool
async def list_available_models() -> str:
    """Fetches the current list of all models available on OpenRouter."""
```

**Why it's a problem:** The whole point of this tool is to be parsed by another LLM, but the output format (plain `- ID: ... | Name: ... | Context: ...` lines) is undocumented, untested, and brittle to upstream schema changes. The comment "Format the output to be token-efficient for the LLM" is an aspiration, not a guarantee.

**Recommendation:** Document the format in the docstring, pin the fields with `.get(...)`, and add a unit test with a mocked httpx response so format changes are caught.

---

## Missing Infrastructure

### MI1. No `requirements.txt`, `pyproject.toml`, `Pipfile`, or any dependency manifest

There is no way for a new contributor (or CI) to install the project. The runtime dependencies are at least `httpx`, `mcp` (or `fastmcp`), and `python-dotenv`, but a `pip install` would have to guess.

**Recommendation:** Add a `requirements.txt` (or preferably `pyproject.toml` with pinned versions) listing at minimum: `httpx`, `mcp`, `python-dotenv`. Consider a lockfile (`uv.lock`, `poetry.lock`, `pip-compile`) so installs are reproducible.

---

### MI2. No `README.md`

There is no project description, no setup instructions, no list of required environment variables, no usage example, and no documentation of what tools the MCP server exposes. A new user has to read both source files to discover the tool names and required env vars (`LLM_API_KEY_DICT` vs `OPENROUTER_API_KEY`).

**Recommendation:** Add a README with: project purpose, install steps, env var reference, example client invocation, and a comparison of `base.py` vs `mcp_server.py` (or — better — a decision about which to keep; see MI5).

---

### MI3. No tests

There are no unit tests, no integration tests, no fixtures, and no test runner config (`pytest`, `unittest`, etc.). Coverage is 0%. The code paths most worth testing — JSON env var parsing, malformed headers, API errors, model-list formatting, retry behavior — are exactly the paths most likely to regress silently.

**Recommendation:** Add at minimum:
- A unit test for env-var parsing (valid JSON, invalid JSON, missing var).
- A unit test for the `mcp_tool` decorator (does `structured_output=False` propagate?).
- An `httpx.MockTransport` test for both tools: 200 success, 401, 429, 500, malformed JSON, network timeout.
- A test for `list_available_models` formatting with a mocked payload.

---

### MI4. No `.env.example` or documented env contract

Neither file documents which env vars it expects (`LLM_API_KEY_DICT`, `OPENROUTER_API_KEY`), the shape of `LLM_API_KEY_DICT` (must be JSON of `str -> str`), or whether `OPENROUTER_URL` is configurable. A `.env.example` is the standard fix.

**Recommendation:** Add `.env.example` with documented, commented-out values, and reference it from the README.

---

### MI5. Two near-duplicate entry-point files with no clear ownership

`base.py` and `mcp_server.py` overlap ~80% (same decorator, same FastMCP instantiation, same async `httpx` POST pattern). They appear to be two iterations of the same idea. Importing both would silently break (see H1). There is no comment, README, or naming convention indicating which one is canonical.

**Recommendation:** Pick one (likely `mcp_server.py` — it's more complete with timeout and error handling) and delete or archive the other. If both are intentionally supported (generic vs OpenRouter), split the shared code into a `common.py` module and give each entrypoint a distinct, meaningful name.

---

### MI6. No CI configuration

No `.github/workflows`, no `tox.ini`, no `pre-commit` config, no lint config (`ruff`, `black`, `mypy`). Without CI, the issues raised in this review have nothing to prevent regression.

**Recommendation:** Add a minimal CI workflow that runs `ruff check`, `mypy`, and `pytest` on every push.

---

### MI7. No request/response logging, no metrics, no tracing

Beyond M1 (no logging), there is no instrumentation: no request IDs, no latency tracking, no token-count logging, no Prometheus/OpenTelemetry hooks. For a server that proxies billable API calls, this is a notable gap.

**Recommendation:** At minimum, log `model`, `base_url`, `latency_ms`, `status_code`, and `response_tokens` per call (never log the API key or full prompt body).

---

### MI8. No graceful shutdown / connection cleanup

```python
async with httpx.AsyncClient() as client:
    response = await client.post(...)
```

**Why it's a gap:** `httpx.AsyncClient()` is created fresh per request (no connection reuse), which is wasteful under load. For a higher-quality implementation, a single shared `AsyncClient` with a lifespan hook on the FastMCP server would reuse connections and shut down cleanly on SIGTERM.

**Recommendation:** Use FastMCP's lifespan/context to construct a single `httpx.AsyncClient` and inject it into the tool calls. Close it on shutdown.

---

## Reviewer Notes

- I treated `base.py` and `mcp_server.py` as two independent files; both have overlapping responsibilities and the codebase as a whole would benefit from consolidation (MI5).
- Severity is calibrated to a small internal MCP wrapper: Critical = security/correctness bug that would bite in production or break importability; High = will cause failures under normal conditions; Medium = reliability/maintainability; Low = polish.
- All line numbers refer to the files as read on the review date and may drift if files are edited.