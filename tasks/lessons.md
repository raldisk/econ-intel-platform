# Lessons Learned

<!-- PH-Dashboard project log -->
<!-- Append new entries at the top — newest first -->

---

## 2026-03-31 — Session 14

### L019 — Architecture diagrams are a first-class deliverable, not documentation afterthought
**Session:** Session 14 — Phase 12 (Polish)
**Pattern:** The nine source repos in PH-DEP each had architecture diagrams. They
showed single-domain flows: one box for the scraper, one for the database, one for
the dashboard. The unified PH Dashboard spans four architectural layers, nine pipeline
columns, three cross-pipeline view dependencies, and a scheduler thread — none of which
is visible from the code alone. A hiring manager reviewing the GitHub repo will see the
SVG before reading a single line of Python.
**Rule:** An architecture diagram for a multi-domain system earns its place in the
repo root or docs/ from day one, not after the code is done. It is the fastest way
to communicate that the system is coherent — that the nine domains share a uniform
E/T/L interface, converge into a single DuckDB, and surface through a shared component
layer. Draw it early; it disciplines the architecture. Update it at each phase. Ship it
as a deliverable in the Polish phase with the same care as the code.

---

## 2026-03-31 — Session 13

### L018 — SQL passthrough panel is the strongest single interview artifact in a data engineering portfolio
**Session:** Session 13 — Phase 10 (Dash) + Phase 11 (COA)
**Pattern:** Every source repo in PH-DEP shipped its own isolated Streamlit dashboard
reading from its own PostgreSQL instance. A hiring manager reviewing three separate
repos sees three separate projects. The Dash SQL passthrough panel forces the
conversation to the cross-domain schema — you can show live queries joining PSX prices,
BSP rate decisions, and CPI inflation in a single SELECT. That is not possible in any
single-domain portfolio project.
**Rule:** When building a multi-domain data platform, allocate explicit design budget
to the cross-domain query surface. A read-only SQL editor against the local DuckDB
costs one callback and one textarea. The return — live demonstration of schema
coherence across nine domains in a technical interview — is asymmetric. Build it
before the charts.

---

## 2026-03-31 — Session 12

### L017 — Shared component layer before page implementations — never inline Plotly in page code
**Session:** Session 12 — Phase 9 (Full Dashboard)
**Pattern:** Source repo dashboards each defined their own color palettes, figure helpers,
and formatter functions inline in the single-file app. The unified dashboard merges
nine domains into one app — inlining those patterns would produce nine copies of
the same `plot_bgcolor` settings and three incompatible color maps for the same
indicators (BSP rate appearing in three different colors across pages).
**Rule:** Extract all figure factories, color constants, column formatters, and
download helpers into `components/` before writing a single page. The component
layer has two invariants: (1) every figure is transparent-background so it
embeds cleanly regardless of Streamlit theme; (2) every domain has exactly one
canonical color key. Adding a page becomes three function calls — no design
decisions required at the page level.

---

## 2026-03-31 — Session 11

### L016 — Build the Status page before wiring the scheduler — observability before automation
**Session:** Session 11 — Phase 7 (Streamlit Status) + Phase 8 (Scheduler)
**Pattern:** Plan v2 originally sequenced Scheduler (Phase 6) before Streamlit (Phase 7).
This was caught and reversed in L009 during Session 3. The correction held: Phase 7
(Status page) was built before Phase 8 (scheduler activation), providing a visible
validation surface for every pipeline run before any automation fires.
**Restatement of L009 with the concrete implementation:** The `pipeline_runs` table
is the bridge. Every load.py writes to it; the Status page reads from it. Without
the Status page, scheduler failures are silent — a `pipeline_runs` error row with
no UI to surface it. The Status page is not a nice-to-have; it is the minimum
observable surface that makes scheduled automation safe to activate.
**Rule:** Never activate a scheduler against a pipeline that does not have at least
one human-readable status surface. The surface does not have to be polished — a
table of pipeline name, last run, status, and row count is sufficient. Build that
first.

---

## 2026-03-31 — Session 10

### L015 — CPU hardware constraints must gate dependency selection before any code is written
**Session:** Session 10 — Phase 6 (Sentiment) — CF-V10-001
**Pattern:** PH-Social-Sentiment-Pipeline was built around transformers+torch
(XLM-RoBERTa multilingual model), confluent-kafka, and faust-streaming. All three
are non-viable on Intel Pentium CPU: torch CPU inference runs 10+ minutes per batch,
making scheduled execution impossible; Kafka requires a broker process that a local
Windows single-machine setup cannot sustain; faust-streaming inherits the Kafka
dependency. Discovering this after attempting to port the architecture would have
wasted a session.
**Rule:** Before porting any pipeline from a source repo, read its requirements.txt
first and cross-check each heavy dependency against the target hardware. If the
primary inference mechanism is GPU-dependent, select the CPU-viable fallback
(VADER, rule-based, or lightweight sklearn model) before writing a single line of
pipeline code. Hardware constraints are architectural constraints — not optimizations.

---

## 2026-03-30 — Session 8

### L014 — Repo name is not domain documentation — always read the source
**Session:** Session 8 — Phase 4 (Labor + Regional) — CF-V8-001
**Pattern:** PH-Labor-Analysis was assumed to contain PSA LFS unemployment/underemployment
microdata based on its name. The actual repo is `ph-ofw-analysis` — a macroeconomic
EDA notebook covering GDP, CPI, and OFW remittances. The exact domain already covered
by the economic pipeline. No LFS data anywhere in the repo.
**Rule:** Never infer domain from repo name. Read the README, inspect actual data files,
and check the sample data column names before declaring a repo's migration scope. Two
repos with similar-sounding names can cover entirely non-overlapping domains.
This is L004 extended: L004 says audit before merge; L014 says the most dangerous
assumption is the one that feels obvious and therefore goes unchecked.

---

## 2026-03-30 — Session 6

### L013 — Speculative phase builds are safe only when the dependency graph is clean
**Session:** Session 6 — Phase 2 (BSP pipeline) — CF-V6-004
**Pattern:** Phase 0.5 gates hadn't run yet when Phase 2 build began. The risk
of speculative work is that a gate failure could invalidate the built artifacts.
In this case, Phase 2's dependency chain — `lib/sources/bsp.py`, `config.py`,
`db/schema.sql`, `lib/db.py` — was entirely verified in prior sessions. Phase 2
had zero dependency on Phase 1's new deliverables (`psa.py`, `ttl_cache.py`).
The speculative build was safe because the dependency graph was provably clean.
**Rule:** Before building Phase N+1 while Phase N's gate is unverified, explicitly
map Phase N+1's dependency chain. If every dependency was verified in a prior
session and Phase N adds none of them, speculative build is safe and should
proceed. Document the dependency check in combined_findings — do not assume it,
derive it. If any new Phase N component appears in Phase N+1's import list, halt
and wait for the gate.

---

## 2026-03-29 — Session 5

### L012 — Match the dependency floor of the receiving module, not the source module
**Session:** Session 5 — Phase 1 — lib/sources/psa.py
**Pattern:** PH-Economic-Tracker's `psa.py` uses `tenacity` and `rich` — both
genuinely useful for PSA API's latency profile. Neither is in `requirements.txt`.
Carrying them over would add two transitive dependency trees (six+ packages) to solve
a problem already handled by the manual retry loop in `lib/sources/bsp.py`.
**Rule:** When porting source logic from a sub-repo into a shared lib module,
check `requirements.txt` first. If the source module's dependencies are not already
present, reimplement using what is available before adding new packages. The cost of
a dependency is not the install time — it is the upgrade chain for the next three years.

### L011 — XML schema validation before execution, not after
**Session:** Session 4 — full-xml-prompt.xml intake
**Pattern:** `full-xml-prompt.xml` had 5 schema violations against
`validation-schema.xml`: tag name mismatches (`session_lineage` vs
`context_lineage`, `pipeline_layers` vs `pipeline`), a missing required
`mission` section, `behavior` standing in for `execution_rules`, and
`readiness_gate` + `execution_phase` sitting outside the pipeline stage
sequence rather than as ordered children of it. None of these caused
execution failure in this session because the intent was unambiguous —
but a strict parser would have rejected the prompt outright.
**Rule:** Run XML prompts against their schema before treating them as
executable. The correction is mechanical (rename tags, add missing
sections, reorder children) but must happen before execution begins, not
be discovered mid-run. `corrected-prompt.xml` is the canonical template
for future sessions.

### L010 — Phase completion requires the verification gate, not just artifact delivery
**Session:** 2026-03-29 — CONTINUATION-V2 post-audit
**Pattern:** Phase 0 was declared COMPLETE after 16 artifacts were produced.
Three of them — a `pyproject.toml` naming issue, `config.py` not re-packaged
into the session zip, and `load.py` entirely absent — prevented Phase 0.5
gates from executing. The phase was complete in intent, not in execution.
**Rule:** A phase is complete when its verification gate passes, not when
its artifacts are delivered. If Phase N.5 is the verification gate for Phase N,
then Phase N is not COMPLETE until Phase N.5 is GREEN. Record status as:
`Phase N — Artifact Delivery ✅ | Phase N.5 — Verification Gate ⬜`
until the gate actually passes locally.

---

## 2026-03-29 — Session 3

### L009 — The phase that builds the app should come before the phase that fires the scheduler
**Pattern:** Plan v2 had Scheduler (Phase 6) before Streamlit (Phase 7). The
scheduler would start firing PSX jobs in Week 4 against unvalidated pipeline
output, with no app surface to inspect the data until Week 5.
**Rule:** Build at least a stub app (Status page) before activating any
scheduled job. The app is the validation surface. Automation without
observability accumulates silent errors.

### L008 — Dead code that returns all-NaN is worse than no function
**Pattern:** `_ma_signal()` in transform.py was never called but contained a
broken implementation that produced all-NaN. It looked like an alternative
implementation rather than dead code.
**Rule:** Delete dead code immediately. Two implementations means one too many.
A broken function waiting to be called is a latent bug.

### L007 — Fatal on bootstrap failure, never advisory
**Pattern:** `init.py` wrapped DDL in try/except that logged a warning and
continued. Silent schema failures produce zero-row dashboard pages with no
error signal.
**Rule:** Schema bootstrap failures are always fatal. An incomplete schema
is worse than no schema — at least no schema fails loudly.

### L006 — ASOF JOIN requires explicit sort on the right-side table
**Pattern:** DuckDB ASOF JOIN requires the right-side table ascending on the
join key. BSP HTML tables are commonly descending. A parquet written from
descending HTML produces silently wrong matches.
**Rule:** Always wrap the right-side table in an `ORDER BY key ASC` CTE.
Never assume parquet write order matches join requirements.

### L005 — Placeholder views prevent first-launch crashes at zero cost
**Pattern:** The COA pipeline correctly used `WHERE 1=0`. All other pipeline
views used `read_parquet('{PATH}')` which raises `IOException` if the parquet
doesn't exist. `load.py` already uses `CREATE OR REPLACE VIEW` which overwrites
the placeholder on first run.
**Rule:** Schema bootstrap views always start as empty-schema stubs. Pipeline
load steps replace them. Never write a parquet-path view directly in schema.sql.

### L004 — Audit before merge: check domain, not just structure
**Pattern:** Plan v2 §2c assumed PH-Price-Tracker and PH-Food-Price-Decomposition
shared the commodity pricing domain based on their names. The actual codebase
showed PH-Price-Tracker is a Lazada e-commerce scraper.
**Rule:** Never declare a domain merge until source files are read. Module
docstrings and dbt mart names tell you what a repo actually does.

---

## 2026-03-29 — Session 1/2

### L003 — Brace expansion in bash_tool requires explicit subshell or eval
**Pattern:** `mkdir -p /path/{a,b,c}` silently fails in bash_tool.
**Rule:** Never use brace expansion in bash_tool commands. Always expand to
individual calls.

### L002 — Read and audit the actual codebase before making architectural claims
**Pattern:** Claimed PH-Social-Sentiment-Pipeline and PH-Food-Price-Decomposition
were "missing from plan" without reading the zip first.
**Rule:** Always extract and audit before making gap claims.

### L001 — Don't suggest removing explicitly requested features
**Pattern:** Suggested removing COA pipeline which user had explicitly requested.
**Rule:** Never suggest removing a feature the user asked for. Defer to a later
phase if needed — never frame it as removal.