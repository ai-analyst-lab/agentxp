# Module 5 — Data plumbing

> **Goal:** Understand how AgentXP touches a real warehouse without (a) letting an
> agent run a destructive query, (b) ever leaking a credential into a log, or (c)
> handing raw customer rows to a judgment agent. By the end you can trace a query
> through every safety layer, name what each layer rejects, and prove the
> credential redactor works by trying to make it fail.

---

## Why (the design reasoning)

The moment your experiment platform connects to a production warehouse, the threat
model changes completely. Now an LLM-proposed string can `DROP TABLE`. A stack
trace can print a Snowflake password. A `SELECT *` can pull 40 million customer
rows into a context window. None of these are hypothetical — they're the default
behavior of a naive "let the agent run SQL" design.

AgentXP's answer is **fail-closed defense in depth**: a query proposed by an agent
passes through a fixed pipeline of checks, and *any* check can reject it before a
single byte hits the warehouse. The agent proposes; deterministic Python disposes.
This is the same thesis line as everywhere else — the LLM does the judgment
("which table, which metric") and Python owns the part where a wrong answer is
catastrophic ("is this query safe to execute").

Two honest framings to carry, because a reviewer will probe them:

- **"5 layers" is the spec framing; the code has 4 numbered layers, with Layer 3
  split into 3a/3b/3c**, plus an unnumbered dialect-hazard guard between parse and
  read-only. Don't oversell a fifth layer that isn't numbered — name the real
  shape.
- **DuckDB is the only *verified* adapter.** Snowflake, BigQuery, and Databricks
  ship `live_unverified`: code-complete, mock-tested, but never run against live
  credentials (Module 7). Naming that boundary is part of looking like an expert.

---

## Walkthrough — the pipeline, the adapters, the redactor

### The safety pipeline (`agentxp/sql/safety.py`)

Entry point: `run_pipeline(sql, dialect, purpose, ...) -> SafetyResult`. The query
flows through these checks **in order**, fail-closed at each:

1. **Layer 1 — parse** (`parse_sql`, delegating to `agentxp/sql/parser.py`, which
   wraps `sqlglot.parse_one`). Empty input, a parse error, or a `None` tree raises
   `UnparseableSQL`. Because `parse_one` parses only the *first* statement,
   single-statement enforcement is implicit here — there's no separate
   "multi-statement gate," so don't claim one.

   *(between 1 and 2)* **`assert_no_dialect_hazard`** — an unnumbered guard. No-op
   except on Databricks, where a recursive CTE is rejected (`DialectHazardViolation`)
   because sqlglot would silently de-recurse it into a non-equivalent query.

2. **Layer 2 — read-only** (`layer_2_assert_read_only`). Walks the AST; any write
   node raises `ReadOnlyViolation: Write / DDL operation not permitted: <Type>`.
   The banned set (`_WRITE_NODES`): `Delete, Drop, Update, Insert, TruncateTable,
   Merge, Create, Alter`. EXPLAIN is allowed (it parses as a `Command`, not a
   write).

3. **Layer 3a — single-adapter** (`layer_3a_assert_single_adapter`). Scans table
   qualifiers; if a query references two different adapter prefixes
   (`snowflake/bigquery/duckdb/databricks`) → `CrossAdapterViolation`. No-op
   without a config.

   **Layer 3b — semantic-model check** (`layer_3b_semantic_model_check`). If
   semantic models are supplied, every table must be a declared `fact_source`,
   else `SemanticModelViolation`.

   **Layer 3c — deny-list + AST allowlist** (`layer_3c_deny_list_check`). Two
   complementary gates. A *function deny-list* (`DENY_FUNCTIONS`) blocks things
   like `PG_SLEEP`, `SYSTEM$WAIT`, `SYSTEM$CANCEL_QUERY`, `COPY`, `LOAD_FILE`,
   `EXEC`/`EXECUTE`/`EVAL`, `BQ.JOBS.CANCEL` → `DenyListViolation: Function '…' is
   on the §11 deny-list`. And an *AST allowlist* (`ALLOWED_AST_NODES` +
   `_STRUCTURAL_ALLOWED`): any node type not on the allowlist →
   `DenyListViolation: AST node '…' is not in ALLOWED_AST_NODES`. A non-EXPLAIN
   `Command` is also rejected. This is the belt-and-suspenders core: deny known-bad
   *and* allow only known-good node shapes.

4. **Layer 4 — resource bounds** (`layer_4_enforce_resource_bounds`). Looks up the
   per-purpose row cap (`_ROW_LIMIT_BY_PURPOSE`: `profile=100k`, `preview=1k`,
   `srm_check=1M`, `metric_compute=10M`, `user_paste=1k`). On a `SELECT` with no
   `LIMIT`, it *injects* the cap; with a `LIMIT` over the cap, it *replaces* it;
   with a tighter `LIMIT`, it leaves your bound alone. Unknown purpose →
   `ResourceBoundsViolation`.

`SafetyResult.layers_passed` records `[1, 2, 3, 4]` (the 3a/b/c collapse into a
single `3`). Every violation subclasses `SafetyViolation`, so the dispatch layer
can catch the whole family.

### The adapters (`agentxp/sql/adapters/`)

Four adapters, one shared `BaseAdapter` Protocol (`agentxp/sql/adapter.py`):
`execute(sql, max_rows, timeout_s) -> AdapterResult`, `explain`, `dry_run`,
`get_dialect`, `close`. A registry (`ADAPTER_REGISTRY`) maps dialect strings to
classes. Shared properties worth knowing:

- **Lazy driver import** — the package imports cleanly with *no* warehouse driver
  installed; a missing driver raises `ImportError` with a credential-free install
  hint.
- **Lazy connect** — no connection until the first `execute`/`explain`/`dry_run`.
- **DuckDB** (verified): connects to `:memory:` or a file; timeout is advisory
  (measured around `fetchall`, no driver cancel). The reference adapter the whole
  test suite runs against.
- **Snowflake / BigQuery / Databricks** (`live_unverified`): real server-side
  timeouts and byte limits, multiple auth surfaces (password / externalbrowser /
  oauth / keypair for Snowflake; ADC/SA-JSON + `maximum_bytes_billed` for BigQuery;
  PAT/OAuth + Unity Catalog naming for Databricks). Auth failures map to
  `AuthExpiredError`; byte ceilings to `BytesLimitExceededError`.

### The credential redactor (two layers)

This is the subsystem you should be able to *prove* works, because a leak here is
the worst-case failure.

- **Key-based redaction** (`_redact_creds_for_log` + `_SENSITIVE_KEYS` in
  `agentxp/sql/adapter.py`). `_SENSITIVE_KEYS` is the single canonical set
  (`password, secret, token, api_key, access_key, secret_key, private_key,
  access_token, client_secret, oauth_token, …`). Any dict value under a sensitive
  key becomes the literal `"[REDACTED]"`, regardless of type; nested dicts recurse;
  non-sensitive strings still pass through the regex redactor. (A code comment
  records that prior *drift* between duplicated key-sets once leaked `access_token`
  / `client_secret` — which is exactly why there's now ONE canonical set.)
- **Regex/structural redaction** (`redact` + `REDACTION_PATTERNS` in
  `agentxp/audit/redactor.py`). Order-sensitive patterns that scrub PEM private
  keys, GCP private-key JSON, AWS keys, JWTs, Bearer tokens, Snowflake connection
  strings (keeps the account, redacts the password), generic `secret=value`,
  emails, and home paths (`/Users/<name>/` → `~/`). Idempotent by construction.
  `redact_message(exc) = redact(str(exc))`.

**Where redaction is applied** (this is the important part): *every* error path in
`agentxp/sql/dispatch.py` runs through `redact_message` before the text touches an
artifact, an audit event, or a `SqlResult` — safety violations, auth errors,
adapter errors, and a catch-all `except Exception` that re-raises a `RuntimeError`
with only redacted text and `from None` (so the unredacted `__cause__` chain is
suppressed). Adapter error messages use only `type(exc).__name__`, never the raw
driver string. Conclusion (for AgentXP-controlled paths): **a credential cannot
reach a log or exception message** — it's enforced at the dispatch chokepoint, not
left to convention.

### Profile security (`agentxp/cli/connect_common.py`)

Credentials live at `~/.agentxp/credentials/{adapter}/{name}.yaml`, written via
`os.open(..., 0o600)` (no world-readable window) with the parent dir at `0o700`.
By default the wizard writes an **`env:VAR_NAME` reference**, not the raw secret —
the secret stays in memory only for the live probe and never hits disk unless you
explicitly opt in. Secrets are collected with `getpass` (no echo), prompts go to
stderr so piped stdout stays clean, and the confirmation print routes the conn
dict through `_redact_creds_for_log` first.

### What the judgment agent never gets

Two bounds protect the context window and the audit trail:

- **Row caps** at two places — Layer 4 caps the SQL `LIMIT`, and `dispatch_sql`
  passes a per-purpose `max_rows`/`timeout_s` to the adapter, which also truncates
  in code.
- **The audit trail stores aggregates, never raw rows** — `QueryResultSummary` is
  schema-documented as "aggregate counts + SRM χ² inputs only — never raw warehouse
  rows," holding a row *count*, a parquet *pointer* + SHA256, and SRM stats. The
  `query.executed` event hashes only `row_count|bytes_scanned`.

Be precise about the boundary: the *audit/artifact substrate is schema-forbidden*
from holding raw rows, and *row caps are enforced* — but there is no single
"schema-only to the LLM" gate inside `agentxp/sql/` itself; that bound lives in
how the orchestrator uses the results. Name what enforces what.

---

## Lab / break-it (attack the warehouse boundary)

**Lab 5a — make Layer 2 reject a write.**
```python
from agentxp.sql.safety import run_pipeline
run_pipeline("SELECT 1; DROP TABLE users", dialect="duckdb", purpose="preview")
```
Expected: `ReadOnlyViolation: Write / DDL operation not permitted: Drop`. (Note
*why*: `parse_one` takes the first statement; the `DROP` is caught by the write-node
walk, not a multi-statement gate.) Try `INSERT`, `UPDATE`, `TRUNCATE`, `MERGE`,
`ALTER`, `CREATE` and watch each fire.

**Lab 5b — trip the function deny-list.**
```python
run_pipeline("SELECT pg_sleep(10)", dialect="duckdb", purpose="preview")
```
Expected: `DenyListViolation: Function 'PG_SLEEP' is on the §11 deny-list`. Then try
`SELECT eval('…')` and a Snowflake `SYSTEM$WAIT`.

**Lab 5c — watch Layer 4 inject a LIMIT.**
```python
from agentxp.sql.parser import parse_sql
from agentxp.sql.safety import layer_4_enforce_resource_bounds
tree = parse_sql("SELECT * FROM t", "duckdb")
print(layer_4_enforce_resource_bounds(tree, "preview").sql())   # → … LIMIT 1000
```
Then pass `purpose="nonsense"` and watch `ResourceBoundsViolation`.

**Lab 5d — prove the redactor (the important one).** Write a fake profile with
`password: hunter2`, then:
```python
from agentxp.sql.adapter import _redact_creds_for_log
print(_redact_creds_for_log({"account": "acme", "password": "hunter2"}))
# → {'account': 'acme', 'password': '[REDACTED]'}
from agentxp.audit.redactor import redact
print(redact("postgresql://user:secretpw@host/db"))   # → …[REDACTED_URL_CREDS]…
```
Then `grep -r hunter2 ~/.agentxp` and confirm the on-disk profile stores
`password: env:AGENTXP_…` (a reference), not the secret. You've proven the leak
path is closed at the key level, the regex level, and the disk level.

(Matching tests: `tests/sql/test_safety.py`, `tests/sql/test_adapter.py`
(`test_redact_creds_for_log_*`), `tests/audit/test_redactor.py`,
`tests/cli/test_connect_wizard.py` for chmod-600 + `env:` references.)

---

## Teach-back checkpoint

You pass Module 5 when you can, without notes:

1. **Trace a query through every layer** — parse → (dialect-hazard) → read-only →
   3a/3b/3c → resource-bounds — and for each say what it rejects and the exception
   it raises. Correct the "5 layers" framing accurately.
2. **Explain why the AST allowlist exists *in addition to* the function
   deny-list** — i.e., why allow-known-good and deny-known-bad are both needed.
3. **Explain the redaction guarantee**: the two redaction layers, the single
   canonical `_SENSITIVE_KEYS` (and the drift incident that justifies it), and why
   a secret can't reach an exception message in the dispatch path.
4. **Name what the audit trail is forbidden to hold** and what enforces the row
   bound — being precise about which boundary enforces what.
5. **State the adapter verification honesty** — which adapter is verified, which
   ship `live_unverified`, and what that term means.

I'll hand you an arbitrary SQL string and ask "which layer kills this, and with
what message?" When you're right every time, check the box and we go to Module 6.
