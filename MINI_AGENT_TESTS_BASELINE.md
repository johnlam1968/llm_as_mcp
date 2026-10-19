# Phase 3 Baseline — Test Rubric for `llm_as_mcp`

**Author:** Hermes (before running Mini-Agent)
**Goal:** Establish what tests *should* exist before evaluating what Mini-Agent produces
**Files under test:** `base.py` (call_another_llm), `mcp_server.py` (call_llm, list_available_models)

## M3's recommended test list (from `MINI_AGENT_REVIEW_M3.md`)

M3 recommended 5 specific test cases:
1. `mcp_tool` decorator preserves wrapped function metadata (`__name__`, `__doc__`, `__wrapped__`)
2. `call_llm` success path returns content
3. `call_llm` 401 raises / returns structured error
4. `list_available_models` formats output correctly and truncates with "more available" indicator
5. `call_another_llm` (base.py):
   - rejects non-http(s) schemes
   - rejects loopback / link-local hosts (mitigates C1)
   - raises when model not in `secret_dict`
   - raises when `secret_dict` is empty

## My expanded rubric — what tests SHOULD exist after Phase 3

### Category T — Behavior tests (must verify behavior, not just import)

| ID | Test case | Why it matters | Severity |
|---|---|---|---|
| T1 | `call_another_llm` with valid api_key, model, query → returns content string | Happy path — proves the function works at all | Critical |
| T2 | `call_another_llm` with model not in `secret_dict` → raises ValueError | The actual error path code (lines 43-44) | Critical |
| T3 | `call_another_llm` rejects http:// (non-https) base_url → raises | Mitigates the SSRF C1 critical | **Critical** |
| T4 | `call_another_llm` rejects loopback hosts (127.0.0.1, localhost, ::1) → raises | Mitigates SSRF C1 critical | **Critical** |
| T5 | `call_another_llm` rejects link-local 169.254.169.254 → raises | Mitigates SSRF C1 (AWS metadata) | **Critical** |
| T6 | `call_another_llm` uses Authorization header with `Bearer ` + api_key | Verifies auth header format | High |
| T7 | `call_llm` with missing OPENROUTER_API_KEY → returns error string | Covers silent error path | High |
| T8 | `call_llm` success path → returns message content | Happy path | High |
| T9 | `call_llm` on 401 response → returns error string (or raises) | Verifies error handling | High |
| T10 | `call_llm` on response missing "choices" key → doesn't KeyError | Verifies response schema assumption | High |
| T11 | `list_available_models` returns formatted list with id/name/context_length | Happy path | Medium |
| T12 | `list_available_models` truncates at 50 with "and N more" indicator | Catches silent truncation bug | Medium |
| T13 | `list_available_models` handles network error gracefully | Error path | Medium |
| T14 | `mcp_tool` decorator preserves function metadata | Verifies decorator doesn't lose `__name__` | Medium |
| T15 | Module imports don't crash when env vars set correctly | Basic importability | Medium |
| T16 | Module imports DON'T crash when env vars missing (graceful fail) | Catches the import-time `sys.exit(1)` bug | High |

### Category M — Mocking correctness (most important meta-test)

A test that "passes" but doesn't actually exercise the code is worse than no test. Score:

- **Good mock**: uses `respx` or `pytest-httpx` to intercept httpx calls, asserts on request shape AND response handling
- **Bad mock**: patches `httpx.AsyncClient` with a stub that always returns the same dict
- **Worse mock**: doesn't mock at all, hits real API (will fail in CI without API keys)

### Category I — Infrastructure (must have)

| ID | Item | Severity |
|---|---|---|
| I1 | `tests/__init__.py` exists (or pytest discovery works without it) | High |
| I2 | `conftest.py` exists with any shared fixtures (env vars, httpx mock) | High |
| I3 | `pytest.ini` or `pyproject.toml [tool.pytest.ini_options]` exists with `asyncio_mode = auto` (needed for `async def` test functions) | Critical |
| I4 | `requirements-dev.txt` or test deps in pyproject: `pytest`, `pytest-asyncio`, `respx` or `pytest-httpx` | Critical |
| I5 | All tests pass when run via `pytest tests/ -v` | Critical (verify-before-declare) |

### Category R — Test runtime behavior (verify-before-declare)

These must be empirically verified after Mini-Agent writes the tests:

| ID | Check | Method |
|---|---|---|
| R1 | `pytest --collect-only` succeeds | Run it |
| R2 | `pytest tests/ -v` exits 0 | Run it |
| R3 | All tests run in <5 seconds total (no real network calls) | Time the run |
| R4 | No test imports `pytest` inside the test function (anti-pattern) | grep |
| R5 | Mocks use a real library (respx / pytest-httpx), not hand-rolled stubs | inspect |

## Scoring rubric

- **Pass threshold**: ≥10/16 behavior tests (T1-T16) present + ≥3/5 infrastructure (I1-I5) + 5/5 runtime (R1-R5)
- **Bonus**: finding T3/T4/T5 (SSRF mitigation tests) — these prove Mini-Agent understood the architectural issue from Phase 1
- **Penalty**: tests that pass without exercising the code (e.g. always-true asserts)

## What I'm NOT testing for in Phase 3

- **Coverage %** — premature for a 156-LOC codebase with no coverage tooling set up
- **Performance** — not relevant for test-writing phase
- **CI integration** — separate concern, deferred
- **Mutation testing** — too expensive for this experiment
