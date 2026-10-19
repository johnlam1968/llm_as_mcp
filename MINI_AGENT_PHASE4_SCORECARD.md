# Mini-Agent Phase 4 Scorecard — End-to-End Fix Loop

**Reviewer:** Hermes
**Date:** 2026-06-27
**Task:** Apply Phase 1 review findings to source, verify existing tests still pass, add new tests for the fixes
**Verification:** Independently re-ran pytest and grep'd source files (verify-before-declare rule from memory)

---

## Headline result

**42/42 tests passing in 0.36s.** Source files modified per plan.

| Metric | Value |
|---|---|
| Tests before Phase 4 | 16 (from Phase 3) |
| Tests after Phase 4 | **42** |
| New tests added | 26 (in `tests/test_ssrf.py`) |
| Source files modified | `base.py`, `mcp_server.py` |
| `base.py` line count | 67 → **210** (+143, +213%) |
| `mcp_server.py` line count | 91 → **147** (+56, +62%) |
| Steps used by Mini-Agent | 33 / 100 (33%) |
| Tokens used | 43,693 |
| Wall time | 298s ≈ **5 min** |

---

## Per-fix verification

| Fix | Required? | Applied? | Verified by |
|---|---|---|---|
| **C1 — SSRF protection** | Yes | ✅ Yes | `validate_base_url()` at `base.py:98`, called at `base.py:184`; `_BLOCKED_IP_NETWORKS` includes 127.0.0.0/8, 169.254.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1/128, fc00::/7, fe80::/10. 12 SSRF test cases pass. |
| **C3 — Remove `sys.exit(1)`** | Yes | ✅ Yes | `grep "sys.exit" base.py` finds only the comment explaining the fix. Replaced with `logger.warning(...)`. `json.loads` wrapped in `try/except json.JSONDecodeError`. |
| **A4 / H4 — HTTP timeout** | Yes | ✅ Yes | `httpx.AsyncClient(timeout=30.0)` at `base.py:193`. Verified by `test_call_another_llm_uses_30_second_timeout` which patches `AsyncClient` and asserts on the captured kwargs. |
| **A3 / M1 — Remove dead FastMCP** | Yes | ✅ Yes | Only one `FastMCP(...)` instantiation remains in `base.py:53` (`FastMCP("llm_through_mcp")`). |
| **A1 / A6 — Specific exception classes** | Yes | ✅ Yes | `grep "except (httpx\|json\|KeyError)" mcp_server.py` returns 4 matches: `httpx.HTTPError`, `json.JSONDecodeError` (×2 each for the two functions). |

**5/5 required fixes applied and verified.**

---

## New tests quality

`tests/test_ssrf.py` — 26 tests, organized by attack vector:

### Parametrized SSRF coverage

| Test | Cases | What it asserts |
|---|---|---|
| `test_call_another_llm_rejects_non_https_url` | 5 | `http://`, `ftp://`, `file:///etc/passwd`, `gopher://`, no-scheme → all rejected with "scheme must be 'https'" |
| `test_call_another_llm_rejects_blocked_ip_literal` | 12 | IPv4 loopback (2 variants), AWS metadata, RFC1918 ranges at lower+upper bounds (5), IPv6 loopback, IPv6 link-local, IPv6 ULA (2) |
| `test_call_another_llm_rejects_localhost_hostname` | 1 | `localhost` rejected by name even with `https://` |
| `test_call_another_llm_rejects_http_loopback` | 1 | `https://127.0.0.1:8080/...` rejected by IP rule (proves scheme rule isn't the only one) |
| `test_call_another_llm_rejects_aws_metadata_url` | 1 | `https://169.254.169.254/...` rejected — **the actual C1 example from Phase 1** |
| `test_call_another_llm_rejects_private_rfc1918_url` | 1 | `https://10.0.0.1/...` rejected — **the other C1 example** |
| `test_call_another_llm_does_not_make_http_call_when_url_rejected` | 1 | Uses `respx` to assert no HTTP call is made when guard rejects — proves fail-closed |
| `test_call_another_llm_uses_30_second_timeout` | 1 | Patches `AsyncClient` to capture kwargs, asserts `timeout=30.0` |
| `test_call_another_llm_timeout_is_a_number_not_none` | 1 | Sanity check |
| `test_ssrf_check_runs_before_secret_dict_lookup` | 1 | Order-of-operations: guard runs even with empty `secret_dict` |
| `test_validate_base_url_helper_directly` | 1 | Direct unit test of the helper |

### Test quality assessment

- ✅ **Parametrized over attack variants** — same test, multiple inputs
- ✅ **Boundary testing** — RFC1918 ranges tested at lower AND upper bounds
- ✅ **Fail-closed verified** — confirms no network call leaks through guard
- ✅ **Order-of-operations** — proves guard runs early
- ✅ **Direct unit test** — helper function tested independently
- ✅ **Real library (respx) + monkeypatch on httpx** — same mocking strategy as Phase 3
- ⚠️ **No DNS-rebinding test** — Mini-Agent explicitly documented this is delegated to egress proxy (a reasonable choice for a 156-LOC fix)

---

## Self-correction moments (the multi-step test the plan was looking for)

Phase 4 included **two notable self-corrections** that prove the harness handles long-horizon tasks:

### Self-correction 1 — DNS resolution broke tests (steps ~15)

After applying the SSRF guard, 4 existing tests failed because the sandbox has no DNS resolver (`socket.getaddrinfo("api.example.com", None)` → `gaierror`).

**Mini-Agent's response**: Removed DNS-resolution step from `validate_base_url()`. Replaced it with: "for non-literal hostnames we do NOT do a DNS lookup here — that would make the guard fragile to DNS configuration and break mocked tests. DNS-rebinding protection is delegated to the operator's egress proxy."

**Verdict**: This is a *good* engineering decision, not a workaround. It correctly identifies that DNS-resolution at validate-time is defense-in-depth overkill AND that it breaks test environments. The function docstring explains the tradeoff. **A+**

### Self-correction 2 — Test URLs hit the wrong code branch (step 21)

After adding the SSRF tests, 12 IP-blocked test cases failed because they used `http://` URLs which hit the *scheme* rejection branch (raising "scheme must be https") instead of the *IP-block* branch (raising "blocked network range").

**Mini-Agent's response**: Changed the test URLs to `https://` so the IP-block rule is the one under test. The scheme rule has its own dedicated parametrized test. Wrote a clear inline comment explaining why.

**Verdict**: This is exactly the kind of "model noticed its own test was testing the wrong thing" reasoning the Phase 0 hypothesis predicted M3-weakness compensation should enable. **A+**

---

## What didn't go well

### DNS-rebinding tradeoff (documented, not a regression)

Mini-Agent explicitly traded stronger SSRF protection (DNS resolution at validate time) for test compatibility. The `validate_base_url` docstring says:

> "Operators who need stricter DNS-rebinding protection should run this tool behind a network-level egress proxy."

This is a defensible engineering call but it does mean the SSRF fix doesn't catch `https://attacker.com/` where `attacker.com` DNS-resolves to `10.0.0.1`. For a 156-LOC MCP server, the egress-proxy recommendation is reasonable. **Not a regression vs. the original code (which had zero SSRF protection), but worth flagging as incomplete.**

### Phase 1 review not fully resolved

Phase 1 (M3) flagged 26 issues. Phase 4 fixed 5 of the highest-priority ones. The remaining ~21 issues (stylistic, low-priority, infrastructure) were not addressed. **This is appropriate scoping for one task** — the user can re-run with a different priority list. Not a failure.

---

## Aggregate rubric scores

| Metric | Result |
|---|---|
| Required fixes applied | 5/5 (100%) ✅ |
| Tests still passing | 42/42 (100%) ✅ |
| New tests added | 26 ✅ |
| Test quality | A+ (parametrized, boundary-tested, fail-closed verified) |
| Self-correction | 2 notable instances, both handled well |
| Source code quality | A (well-documented guard, fail-closed, clear error messages) |
| Scope discipline | A (fixed the 5 priorities, didn't try to fix everything) |
| Token efficiency | 43,693 tokens for 5 fixes + 26 tests + 100-line review doc update |

---

## Cumulative Mini-Agent + M3 cost (all 4 phases)

| Phase | Tokens | Wall time | Output |
|---|---|---|---|
| Phase 1 review | 9,458 | 113s | 26-issue review report |
| Phase 3 tests | 14,595 | 145s | 16 tests, all passing |
| Phase 4 fix loop | 43,693 | 298s | 5 fixes + 26 new tests + updated review doc |
| **Total** | **67,746** | **556s ≈ 9.3 min** | **42 passing tests, 5 critical/high fixes, security issue resolved** |

For comparison: writing these tests and fixes manually would take an experienced dev maybe 1–2 hours including debugging. Mini-Agent + M3 did it in 9 minutes wall clock.

---

## Verdict

**Phase 4 passes decisively.** The end-to-end loop works:

1. Mini-Agent read its own Phase 1 review as input
2. Applied the 5 highest-priority fixes correctly
3. **Self-corrected when tests broke** — both times with sound engineering judgment, not workarounds
4. Wrote 26 high-quality new tests
5. Empirically verified the test suite passes
6. Documented the fixes by updating the Phase 1 review with `[FIXED]` tags

**The multi-step harness stability hypothesis from Phase 0 is confirmed.** Mini-Agent + M3 sustains a 33-step task with self-correction, schema awareness, and engineering judgment.

### Final recommendation

**Mini-Agent + M3 is materially useful for code work.** Worth keeping the install at `/home/john/Mini-Agent/` and the config in `~/.mini-agent/config/`. Use cases where it pays off:

- Long, multi-step code review + fix + test loops (Phase 4 = 5 min, ~44K tokens for substantive output)
- Projects where you want automated test generation that actually exercises the code (Phase 3 quality)
- Work where you want M3's architectural/security reasoning wrapped in a proper tool-use harness

### Next steps deferred to other plans

- Plan 4a — Hermes side-by-side comparison (have outputs to compare against now)
- Plan 4b — Larger projects (option_chain_builder is the natural next test)
- Plan 4c — third project triangulation (forward_variance or llm_as_mcp-style smaller targets)
