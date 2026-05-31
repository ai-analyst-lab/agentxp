# Module 9 — Extend it (the build-to-break module)

> **Goal:** Stop *reading about* the system and *change* it. By the end you have
> added a warehouse adapter, added a step to the verdict tree, and touched the
> stage enum — and for each one you can name, before you run anything, exactly which
> guardrail will catch you if you do it wrong. This is the module that turns "I can
> defend it" into "I can extend it without breaking the spine."

---

## Why (the design reasoning)

Every prior module taught you to *defend* a decision someone else made. Real
ownership is the next thing over: can you make a change and know — in advance —
what it will break and what will catch the break? A system is only as trustworthy
as its ability to stop *you*, its author, from quietly corrupting it. You've
watched the guardrails refuse a hand-edited log (Module 4). Now you find out
whether they refuse *you* when you extend the code.

The method for this whole module is one move, repeated:

> **Aha — predict the blast radius, then run the suite.** Before you touch a line,
> write down which tests and which invariants *should* fail if your change is wrong.
> Then make the change and run `pytest`. The gap between your prediction and the red
> output is the exact shape of a coupling you didn't fully understand yet.

This is the opposite of a flashy demo. A demo shows the happy path working. This
shows you the *unhappy* path — the change that's subtly wrong — and proves the
system catches it. That's the only evidence that "extensible without breaking the
spine" is true and not marketing.

One distinction to hold the whole way through: **not every extension is policed by
the same guardrail.** Adding an adapter is caught by the adapter Protocol + the
adapter-matrix tests. Adding a verdict is caught by the *coherence* tests, not by
`validate_chain` (the chain doesn't care what the verdict is). Changing a stage is
caught by the *closure* tests and the canonical-name table. Knowing *which* wall
catches *which* mistake is the real content here.

---

## Lab A — add a warehouse adapter

**The contract.** Every adapter satisfies the `BaseAdapter` Protocol in
`agentxp/sql/adapter.py` (`@runtime_checkable`): `execute(sql, max_rows, timeout_s)
-> AdapterResult`, `explain(sql) -> str`, `dry_run(sql) -> PreviewResult`,
`get_dialect() -> str`, `close() -> None`. The registry that maps a dialect string
to a class is `ADAPTER_REGISTRY` in `agentxp/sql/adapters/__init__.py`.

**Build it (a real, runnable one): an in-memory SQLite adapter.** SQLite ships with
Python, so unlike Snowflake you can actually verify this one end to end.

1. Create `agentxp/sql/adapters/sqlite_adapter.py` with a `SqliteAdapter` class that
   implements the five Protocol methods. **Import `sqlite3` lazily** — inside the
   method that first needs a connection, never at module top — to honor the
   "package imports with no driver installed" rule the other adapters follow (read
   `duckdb_adapter.py` first; mirror its lazy-connect shape).
2. Register it: add `"sqlite": SqliteAdapter` to `ADAPTER_REGISTRY` and export the
   class in `__all__`.

**Predict the blast radius first.** Before running anything, write down your
answers:

- If you forget to implement `dry_run`, what fails — an import error, a Protocol
  check, or a test? (Hint: `@runtime_checkable` Protocols only check *method
  presence* at `isinstance` time, not signatures. So a *missing* method is caught
  by any `isinstance(x, BaseAdapter)` assertion; a *wrong signature* is not — it
  fails later, at call time, in the adapter-matrix test.)
- Does adding `"sqlite"` to the registry break the SQL safety layer (Module 5)?
  (It shouldn't — Layer 3a keys off the adapter *prefix* set
  `snowflake/bigquery/duckdb/databricks`. Your new dialect isn't in that set, which
  is itself a finding: the cross-adapter guard would need updating if you wanted
  sqlite to participate in single-adapter enforcement. **Name that gap; don't paper
  over it.**)

**Run it.**

```bash
$ .venv/bin/python -m pytest tests/sql/ -q          # did anything go red?
$ .venv/bin/python -c "from agentxp.sql.adapters import ADAPTER_REGISTRY; \
    a = ADAPTER_REGISTRY['sqlite'](); print(a.get_dialect())"
```

**The lesson.** A Protocol is a *structural* contract, not a nominal one — you
don't subclass `BaseAdapter`, you just match its shape, and `@runtime_checkable`
turns "matches the shape" into a testable assertion. The adapter boundary is the
easiest extension in the system precisely because the contract is narrow (five
methods) and the registry is one dict. Compare that to Lab C, where the coupling is
wide.

---

## Lab B — add a step to the verdict tree

This is the one people get wrong, because they assume `validate_chain` or some
integrity wall guards the verdict. It does not. **The verdict's correctness is
guarded by the *coherence* tests and the canonical-name table, not by the chain.**

**The target.** Suppose product wants a new verdict: `SHIP-MONITORED` — "ship it,
but the late-window effect was borderline, so watch it." Today that case folds into
`LIFT-WITH-CAVEAT (novelty)` at Step 7 (Module 3). You want to split it out.

**What you must touch (trace it before you type):**

1. **`agentxp/interpret/tree.py`** — add `"SHIP-MONITORED"` to the `Verdict` Literal
   (lines 29-38), and add the branch logic in `walk_tree` Step 7 that returns it
   (e.g. `0.5 <= late_ratio < 0.7` → `SHIP-MONITORED` instead of folding into
   novelty). Predict: does the existing Step 7 test in `tests/interpret/test_tree.py`
   still pass, or does your new boundary change a value it asserts?
2. **`tests/coherence/test_canonical_names.py`** — find the row
   `("Verdict", "literal_contains", "agentxp.interpret.tree", { …8 strings… })`
   around line 187. This `literal_contains` check asserts the Literal *contains*
   the canonical set. Adding a 9th value **passes** this check (the 8 are still
   there) — but if the project's intent is "the verdict set is *closed at 8*," the
   honest move is to update this table *and* the source-of-truth plan (`§1.8.17`)
   so the new value is canonical, not a stowaway.
3. **The readout (Stage 8).** The readout has to be able to render the new verdict.
   Grep for where verdicts become human prose and confirm there's a path for
   `SHIP-MONITORED`, or it'll render as an unhandled case.

**Predict the blast radius.** Which of these fails first if you *only* edit the
Literal and the `walk_tree` branch but forget the readout and the plan?

- `tests/interpret/test_tree.py` — only if your new branch changes an asserted
  verdict/step for an existing fixture.
- `tests/coherence/test_canonical_names.py` — the `md:` plan-string rows fail if you
  claimed the value is canonical but didn't add it to the plan doc; the
  `literal_contains` row does **not** fail on an addition.
- A readout test — if one asserts every verdict has a render path.

**Run it.**

```bash
$ .venv/bin/python -m pytest tests/interpret/ tests/coherence/ -q
```

**The lesson.** The verdict tree is *deterministic and replayable* (Module 3), so
the thing protecting it is "does the closed set stay coherent across `tree.py`, the
plan, and the readout" — a **coherence** property, enforced by tests that compare
names across files. `validate_chain` never enters this picture, because the chain
proves *how* you got to a verdict, not *which* verdict is correct. Extending the
tree teaches you that the system has *different* integrity mechanisms for different
kinds of "wrong," and reaching for the wrong one (expecting the chain to catch a bad
verdict) is itself the misconception.

---

## Lab C — touch the stage enum (the widest coupling)

**Don't fully add a stage** — wiring a real new stage (agent, gate, artifact, DAG
transition, `_commit_stage` call) is a genuine project, not a lab. Instead, make the
*smallest* change to the `Stage` enum and let the test suite show you the blast
radius. That blast radius *is* the lesson.

**The change.** In `agentxp/schemas/state.py`, the `Stage` enum (line 121) has 12
members (the 11 stages + the `brief_contradicted` 3b substate). Try **renaming** one
value — say `MONITOR = "monitor"` to `MONITOR = "monitoring"`.

**Predict, in writing, what goes red:**

- The closure machinery right below the enum (lines 138-145) sets lowercase
  attribute aliases (`Stage.monitor`) from the `.value` strings, so the alias
  becomes `Stage.monitoring`. Anything referencing `Stage.monitor` by its old string
  breaks.
- `tests/coherence/test_canonical_names.py` pins canonical stage names — a renamed
  value diverges from the plan's canonical string and fails.
- `STAGES.md` / the orchestrator spec and any `state.yaml` on disk now disagree with
  the enum, so a *resume* from an old experiment (Module 6) would not recognize the
  stage.

**Run it and read every failure.**

```bash
$ .venv/bin/python -m pytest -q          # expect a cluster of red across coherence + state
```

Now **revert** the rename (`git checkout agentxp/schemas/state.py`) and confirm
green returns.

**The lesson.** The stage enum is the most *load-bearing name* in the system: it's
referenced by the orchestrator, the events, the state file, the resume logic, the
plan, and the coherence tests. That's why the codebase pins it with a closure test
and a canonical-name table — so a one-character rename can't silently propagate. The
width of the red you just saw is the system telling you, honestly, "stages are not a
casual edit." Contrast with Lab A's adapter (narrow contract, one dict) — *the
breadth of the guardrail matches the breadth of the blast radius.* That proportion
is a design choice, not an accident.

---

## Teach-back checkpoint

You pass Module 9 when you can, without notes:

1. **Add the SQLite adapter** and explain why a *missing* method and a *wrong
   signature* fail at different times (Protocol presence-check vs call-time), and
   name the one place (Layer 3a's adapter-prefix set) that would need updating for a
   new dialect to participate in cross-adapter enforcement.
2. **Add a verdict and say what guards it** — explain why the coherence tests and
   the canonical-name table, *not* `validate_chain`, are what catch a bad verdict
   extension, and what "the verdict set is closed at 8" obligates you to update.
3. **Predict the stage-rename blast radius** — name at least three things that go
   red, and explain why the breadth of that guardrail is proportional to how
   load-bearing the stage enum is.
4. **State the module's one rule** — predict the blast radius, then run the suite —
   and why that's the discipline that keeps an extension from quietly breaking the
   spine.

I'll hand you a proposed change ("add a `redshift` adapter," "split `LEARN` into two
verdicts," "add a Stage 4.5") and ask: *what do you touch, what catches you if you're
wrong, and is that the chain, the coherence tests, or the closure tests?* When you
route each change to the right guardrail every time, you can extend AgentXP — check
the box and go to the capstone (Module 8) if you haven't, or to "Where to go after
v0.1."
