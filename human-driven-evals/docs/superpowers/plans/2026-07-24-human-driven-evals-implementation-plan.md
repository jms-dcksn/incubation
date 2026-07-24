# Human-Driven Evals — Implementation Plan

**Date:** 2026-07-24
**Spec:** [`docs/superpowers/specs/2026-07-20-human-driven-evals-design.md`](../specs/2026-07-20-human-driven-evals-design.md)
**Status:** Ready to implement

## How to use this plan

This plan is written to be executed by an implementer with no prior context beyond the spec. Work the phases in order. **Each phase ends in a committable, demonstrable state** — do not start the next phase until the current one's "Definition of done" is green.

Two rules carried from the spec drive the ordering:

1. **The two load-bearing risks are the seeded critiques and judge-synthesis quality.** Both are unproven until built. So Phase 2 writes the critiques and Phase 3 is a *thin vertical slice* — one failure mode from label to alignment — before any of the seven screens are built out. If the slice is weak, we learn it on day 3, not day 30.
2. **Screens 2 (Label) and 5 (Alignment) carry the argument.** They get disproportionate build and polish effort (Phases 5 and 9).

**Testing posture:** pure logic (DSL interpreter, alignment math, split/holdout, cost guards, session seeding) is built test-first (RED → GREEN → REFACTOR). Agent calls (clustering, synthesis, misalignment) are validated with *golden-fixture harness tests* — checked-in inputs, asserted structural properties of the output, run against the live model behind a flag — not brittle exact-match. UI is verified with Playwright happy-path scripts plus a manual demo checklist per screen.

**Definition of "demoable":** the running app on `localhost:3000` (or the Vercel preview) shows the phase's new capability end-to-end without hand-editing the database.

---

## Architecture at a glance

```
Next.js App Router (Vercel)
├── app/                         # screens (route per screen) + route handlers (API)
│   ├── (screens)/runs, /label, /taxonomy, /evaluators, /alignment, /improve, /payoff
│   └── api/…                    # agent-call streaming endpoints + mutations
├── lib/
│   ├── db/                      # Drizzle schema + client (Neon Postgres)
│   ├── session/                 # cookie-keyed session, seeding, stage machine
│   ├── fixtures/                # static data: employees, policy, 40 traces, 26 critiques
│   ├── trace/                   # trace type + step accessors (shared by UI + DSL)
│   ├── dsl/                     # zod AST schema + interpreter + binding trace
│   ├── judges/                  # LLM judge runner + DSL judge runner + composite verdict
│   ├── agents/                  # clustering, synthesis, misalignment (Anthropic SDK)
│   ├── alignment/               # agreement %, Cohen's κ, per-judge FP/FN, split
│   └── anthropic/               # SDK client, model config, streaming helper
└── components/                  # trace pane, critique editor, judge card, tuner, etc.
```

**Data ownership:**
- **Static, in-repo (never in DB):** employees, policy handbook, the 40 traces, the 26 Priya critiques, the build/holdout split assignment. These are fixtures committed as JSON/TS.
- **Per-session, in DB:** the session row + stage, the visitor's ~8 labels (plus the 26 seeded rows copied in at session creation), the ratified taxonomy, the synthesized judges, judge-run results, improvement proposals, iteration counter.

**Models** (from spec §8): LLM judges `claude-haiku-4-5` (no thinking); clustering/synthesis/misalignment `claude-opus-4-8` with `thinking: {type:"adaptive"}`, `output_config:{effort:"high"}`. Long agent calls stream reasoning to the UI.

---

## Phase 0 — Foundation & deploy skeleton

**Goal:** an empty-but-deployed Next.js app with DB, session cookie, and a health route, live on a Vercel preview. Everything downstream builds on this; get the pipeline green before writing features.

**Tasks**

1. Scaffold Next.js (App Router, TypeScript, Tailwind) at repo root of `human-driven-evals/`. Add `package.json`, `tsconfig`, ESLint/Prettier, `vitest` for unit tests, `@playwright/test` for e2e (use the pre-installed Chromium at `/opt/pw-browsers/chromium`; do **not** run `playwright install`).
2. Add Neon Postgres + Drizzle. `lib/db/client.ts`, `lib/db/schema.ts` (empty for now), `drizzle.config.ts`, and `npm run db:push` / `db:migrate` scripts. Store `DATABASE_URL` in `.env.local` (gitignored) and Vercel env.
3. Add `lib/anthropic/client.ts`: SDK client reading `ANTHROPIC_API_KEY`, plus `lib/anthropic/models.ts` exporting the two model configs and a `streamReasoning()` helper (SSE) used by later phases.
4. Session middleware: `lib/session/cookie.ts` sets a signed cookie `hde_session` on first request; `middleware.ts` ensures every request has one. No auth.
5. `GET /api/health` returns `{ ok: true, db: <bool>, session: <id> }`. Add `app/page.tsx` that redirects to `/runs` (stubbed).
6. Wire Vercel: `vercel.json` if needed, connect the repo, confirm the preview builds and `/api/health` returns `db:true` against Neon.

**Test-first:** `lib/session/cookie.test.ts` — a fresh request with no cookie gets one; an existing cookie is preserved.

**Definition of done:** Vercel preview URL loads, `/api/health` shows `db:true` and a session id, and re-loading keeps the same session id. Committed and pushed.

---

## Phase 1 — Domain fixtures, trace model & DSL types

**Goal:** all static data and the shared type system exist and are validated. No UI yet. This unblocks everything.

**Tasks**

1. **Domain data** (`lib/fixtures/`): `employees.json` (~30 records: name, tenure, location, employment type, accrued leave, remaining balance) and `policy.json` (~15 clauses: parental leave, carry-over caps, jurisdiction entitlements, notice periods). Give clauses stable ids so a judge can check "citation-in-source."
2. **Trace model** (`lib/trace/types.ts`): a `Trace` = `{ run_id, question, steps: Step[], final_answer }`. `Step` is a discriminated union: `user_message`, `tool_call` (`tool`, `args`), `tool_result` (`tool`, `ok`, `data | error`), `assistant_message`, `final_answer` (`text`, plus any extracted structured fields e.g. `stated_days`). Add zod schema `traceSchema` and a `validateTrace()` used by a fixtures test.
3. **Step accessors** (`lib/trace/accessors.ts`): `selectStep(trace, {kind, tool?})` and `getPath(value, path)` — the single source of truth the DSL interpreter *and* the trace-pane UI both use to resolve `accessor` nodes. Unit-tested.
4. **The 40 traces** (`lib/fixtures/traces/*.json`): generate offline (a throwaway script calling the real agent tools against the domain data is fine, but the committed output is hand-curated). ~35% (≈14) exhibit ≥1 planted failure; each of the 5 planted modes (spec §1) appears across multiple runs. Record, per run, a **non-shipped** annotation file `lib/fixtures/planted.json` mapping `run_id → mode[]` — used only to sanity-check clustering during dev, never surfaced in the product.
5. **Build/holdout/unlabelled split** (`lib/fixtures/split.ts`): deterministic assignment — 20 build, 14 holdout, 6 unlabelled (spec §2). Assert counts and disjointness in a test.
6. **DSL AST types** (`lib/dsl/ast.ts`): zod schemas for the ~6 node types (spec §4): `accessor`, `literal` (optional numeric `tolerance`), `compare` (`eq|neq|gt|lt|gte|lte`), `exists`/`notExists`, `and`/`or`/`not`, `contains`. Export `Judge` DSL type = a validated AST root.

**Test-first:** `traces.test.ts` (all 40 parse against `traceSchema`; planted-count ≈35%; every planted mode used ≥2×), `split.test.ts`, `accessors.test.ts`, `ast.test.ts` (valid ASTs parse, malformed ones reject).

**Definition of done:** `npm test` green; a `scripts/inspect-fixtures.ts` prints the corpus summary (counts per mode, split sizes). Committed.

---

## Phase 2 — Seeded critiques (the load-bearing asset)

**Goal:** the 26 Priya critiques exist, read as genuinely human, and — verified against the *real* clustering agent — produce four clean clusters plus the one deliberately ambiguous cluster (modes 1 & 2 conflated). Per spec §2 and §9 this is written **before** the screens and iterated against the live agent.

> This phase deliberately precedes a working clustering UI. It uses a CLI harness so we can iterate critiques ↔ clustering fast.

**Tasks**

1. `lib/fixtures/critiques.ts`: 26 labels `{ run_id, verdict, critique, author:'priya' }` (+ leave room for the ~8 visitor labels added at runtime). Vary phrasing, length, register. Critiques for modes 1 (fabricated clause) and 2 (wrong employee) must both read as *"it told me something untrue about my leave"* so the agent lumps them and a human must split them.
2. `lib/agents/clustering.ts` (first cut): Opus 4.8 call that takes N labels and returns a taxonomy — `{ modes: [{ name, description, member_run_ids, representative_critiques }] }`, zod-validated output. Prompt: unsupervised structure discovery over verdict+critique, no imposed categories (spec §2).
3. `scripts/eval-clustering.ts`: runs clustering over the 26 seeded critiques and prints modes + members, diffed against `planted.json`. This is the dev loop.
4. **Iterate** critiques ↔ clustering until: 4 clean clusters (modes 3, 4, 5, and the {1,2} blob) emerge stably across 3 runs, with {1,2} reliably conflated. Capture the final agent output as a golden fixture `lib/agents/__fixtures__/clustering-seeded.json`.

**Harness test:** `clustering.harness.test.ts` (flagged, live-model): asserts *structural* properties — 4±1 clusters, modes 3/4/5 separated, modes 1&2 share a cluster, every run_id assigned. Not exact-string match.

**Definition of done:** `scripts/eval-clustering.ts` reliably yields the designed taxonomy incl. the ambiguous cluster; golden fixture committed; a short `docs/superpowers/notes/critiques-tuning.md` records what phrasings were load-bearing. Committed.

---

## Phase 3 — Thin vertical slice (risk retirement)

**Goal:** prove the whole thesis for **one** failure mode, end to end, with minimal UI. Per spec §9 this retires both big risks (critiques + synthesis) before the fan-out into seven screens.

Pick **mode 3 (arithmetic error)** as the slice — it's deterministically checkable, so it exercises the DSL path (interpreter, binding trace, live tuning) which is the harder-to-fake half. (We'll add an LLM-judge slice check at the end of the phase using mode 1.)

**Tasks**

1. **DSL interpreter** (`lib/dsl/interpret.ts`, ~200 lines, spec §4): evaluate an AST against a `Trace`, producing `{ verdict: fail|pass, bindingTrace }`. The **binding trace** records, per accessor, the resolved value, source step index, and each comparison's operands + result. Built strictly test-first — this is the interaction that makes the demo tactile.
2. **Synthesis agent** (`lib/agents/synthesis.ts`, first cut): Opus 4.8 call taking one ratified mode + its member critiques + a couple of example traces, returning a judge. It must **choose** LLM vs DSL itself and, for DSL, emit a validated AST (spec §4 — the LLM/code split is not hardcoded). Zod-validate; on invalid AST, one repair round.
3. **Judge runners** (`lib/judges/`): `runDslJudge(ast, trace)` (wraps interpreter) and `runLlmJudge(prompt, trace)` (Haiku, returns `{verdict, evidenceSpan, confidence}`). `compositeVerdict(judgeResults)` = fail if any fires (spec §4).
4. **Alignment math** (`lib/alignment/score.ts`): over the 14 holdout runs, compute agreement %, **Cohen's κ** (spec §5), and per-judge FP/FN. Pure, test-first with hand-worked fixtures (incl. the degenerate "always pass" case κ≈0).
5. **Minimal CLI/route** `scripts/slice.ts`: seeded critiques → clustering → (auto-pick the mode-3 cluster) → synthesis → run judge on holdout → print alignment + one rendered binding trace. No real screens.
6. **LLM-judge spot check:** run synthesis on the mode-1 cluster; confirm it produces a sensible LLM judge and it scores non-trivially on holdout. This de-risks the LLM path too.

**Test-first:** `interpret.test.ts` (each node type; binding trace correctness; numeric tolerance), `score.test.ts` (agreement, κ incl. degenerate, FP/FN), `synthesis.harness.test.ts` (flagged: mode-3 cluster → valid DSL AST that fires on the planted-arithmetic runs and not on clean ones).

**Definition of done:** `scripts/slice.ts` prints, for mode 3, alignment ≥ a sane bar on holdout with a correct inline-bound assertion; the mode-1 spot check produces a working LLM judge. If synthesis quality is weak here, **stop and fix the prompt** before Phase 4 — this is the go/no-go gate. Committed with a short `slice-results.md`.

---

## Phase 4 — DB schema, session lifecycle & Runs screen (Screen 1)

**Goal:** the persistent per-session model exists and the first real screen renders. From here the vertical slice's logic gets wired to UI.

**Tasks**

1. **Drizzle schema** (`lib/db/schema.ts`): `sessions(id, cookie_key, stage, iteration, is_showcase, created_at)`, `labels(id, session_id, run_id, verdict, critique, author)`, `failure_modes(id, session_id, name, description, member_run_ids, ratified, origin)`, `judges(id, session_id, mode_id, type, prompt, ast, approved)`, `judge_runs(id, session_id, judge_id, run_id, verdict, evidence, confidence, binding_trace)`, `proposals(id, session_id, judge_id, type, payload, motivating, applied)`. `db:push`.
2. **Stage machine** (`lib/session/stage.ts`): enum `runs → labelling → taxonomy → evaluators → alignment → improve → payoff`; helpers to read/advance, test-first.
3. **Session seeding** (`lib/session/seed.ts`): on first touch, copy the 26 Priya labels into `labels` for that session. Test-first: a new session has exactly 26 `author:'priya'` rows and stage `labelling`.
4. **Showcase sessions** (spec §7): a deep-linkable seed that fast-forwards a session to a chosen frozen stage (pre-taxonomy / pre-evaluator / post-alignment) from cached artifacts. `lib/session/showcase.ts` + `?showcase=<stage>` entry. (Populate the cached artifacts as later phases produce them; stub now, fill incrementally.)
5. **Screen 1 — Runs** (`app/runs/page.tsx`): dataset overview, label progress (26/34 pre-seeded → visitor target), entry point to labelling. Reads from DB via a server component.

**Test-first:** `stage.test.ts`, `seed.test.ts`. **e2e:** Playwright — fresh visit lands on `/runs`, shows 40 runs and "26 labelled".

**Definition of done:** visiting `/runs` in a fresh session shows the seeded progress; a `?showcase=` link jumps stage. Committed.

---

## Phase 5 — Label screen (Screen 2) — *argument-carrying, high effort*

**Goal:** the keyboard-driven labelling experience where a stranger can catch a failure in <30s (spec §1, §3). This is one of the two screens that carry the argument — invest here.

**Tasks**

1. **Trace pane** (`components/TracePane.tsx`): renders the full trace — user turn, each tool call + tool result, assistant messages, final answer. Tool results show the **underlying source record** (employee record / policy clause) so fabrications and wrong-record errors are catchable by eye (spec §3). Uses `lib/trace/accessors` for field display.
2. **Label form** (`components/LabelForm.tsx`): verdict pass/fail + freeform critique only — **no tags, no categories** (spec §2, the thesis). Keyboard-driven: `f`/`p` verdict, focus critique, `enter`+`n` to save & advance.
3. **Mutations:** `POST /api/labels` upserts a visitor label; advances the run cursor. Guard: visitor labels capped/soft-targeted at ~8; author always `'visitor'`.
4. **Progress + advance:** move through the ~8 unlabelled-by-visitor runs; when the visitor target is met, surface "derive taxonomy" CTA that advances stage → `taxonomy`.

**Test-first:** `POST /api/labels` handler test (persists, sets author, respects run). **e2e:** Playwright — label 3 runs by keyboard, verify persistence and cursor advance; assert a fabricated-clause run visibly shows the policy source so the fabrication is spottable.

**Definition of done:** a visitor can label the visitor slice entirely by keyboard, sees progress, and unlocks Gate-1 entry. Demo-polished (spacing, focus states, no layout shift). Committed.

---

## Phase 6 — Clustering wired + Taxonomy ratification (Screen 3, Gate 1)

**Goal:** the human ratifies the derived taxonomy. Clustering reads **all 34** labels (spec §2 — nothing to leak, it's unsupervised + human-ratified).

**Tasks**

1. **Streaming clustering endpoint** (`app/api/cluster/route.ts`): calls `lib/agents/clustering` (Phase 2) over all 34 labels, **streaming its reasoning** to the UI (spec §8) rather than a spinner. Persists resulting `failure_modes` (unratified).
2. **Screen 3 — Taxonomy ratification** (`app/taxonomy/page.tsx`): one card per proposed cluster with its member critiques shown. Actions: **approve / rename / split / merge** (spec §1 Gate 1). Split/merge mutate `failure_modes` rows. The {1,2} ambiguous cluster is where split earns its keep.
3. **Mutations** (`/api/taxonomy/*`): rename, split (one mode → two, re-assign members), merge (two → one), approve-all → mark ratified, advance stage → `evaluators`.

**e2e:** Playwright — run clustering (mock the agent with the Phase-2 golden fixture in test to stay deterministic/cheap), then **split** the ambiguous cluster into two and approve; assert two ratified modes persist.

**Definition of done:** from a fully-labelled session, the visitor derives a taxonomy, splits the deliberately-ambiguous cluster, and ratifies — with reasoning streamed live. Freeze this state as the **pre-evaluator showcase** artifact. Committed.

---

## Phase 7 — Synthesis wired + Evaluator review (Screen 4, Gate 2)

**Goal:** one judge per ratified mode, synthesized from the **build set (20)** only (spec §2), each human-approved. LLM and DSL judges both first-class.

**Tasks**

1. **Streaming synthesis endpoint** (`app/api/synthesize/route.ts`): for each ratified mode, calls `lib/agents/synthesis` (Phase 3) with member critiques + build-set example traces, streaming reasoning. Persists `judges` (unapproved) — type + prompt or AST.
2. **Screen 4 — Evaluator review** (`app/evaluators/page.tsx`): one card per mode — proposed **judge type + agent rationale**, and the prompt (LLM) or the **rendered assertion** (DSL). Actions: **approve / edit / flip type** (spec §3, Gate 2).
3. **DSL assertion renderer** (`components/DslAssertion.tsx`): renders the AST with resolved values bound inline (spec §4):
   `leave_balance.days_remaining ⟨14⟩ == final_answer.stated_days ⟨12⟩ ✗`, each leaf **clickable → scrolls the trace pane to the source step**. Reuses the binding trace.
4. **Edit forms:** LLM prompt textarea; DSL structured edit (change comparison / threshold / accessor / tolerance) validated against `lib/dsl/ast`. "Flip type" re-invokes synthesis constrained to the other implementation.
5. Approve-all → advance stage → `alignment`.

**Test-first:** DSL edit form → AST round-trips through zod; flip-type produces a valid judge of the other kind. **e2e:** approve a DSL judge and an LLM judge, edit one DSL threshold, confirm persistence.

**Definition of done:** every ratified mode has an approved judge; DSL cards render inline-bound assertions with click-to-trace; reasoning streamed. Committed.

---

## Phase 8 — Judge execution + Alignment screen (Screen 5) — *argument-carrying, high effort*

**Goal:** the second argument-carrying screen. Alignment on the **14 holdout runs**, with **live tuning** for DSL judges (spec §4, §5). This is the most persuasive interaction — invest here.

**Tasks**

1. **Evaluator run** (`app/api/evaluate/route.ts`): run all approved judges over the 14 holdout runs. LLM judges → Haiku, one call per (judge×run), persist verdict/evidence/confidence. DSL judges → interpreter, persist verdict + binding trace. `compositeVerdict` per run.
2. **Screen 5 — Alignment** (`app/alignment/page.tsx`): headline **Agreement % + Cohen's κ** (spec §5, κ guards the degenerate "always pass"). Per-judge **FP/FN** counts. **Disagreement list**: each row = trace + human verdict/critique vs judge verdict/evidence.
3. **Live tuning** (spec §4 — the signature interaction): for DSL judges, the edit form (threshold / comparison / accessor / tolerance) recomputes alignment across all 14 holdout runs **instantly, client-side** (DSL eval is microseconds — no server round-trip, no LLM cost). Runs that flip verdict **animate** in the disagreement list. LLM judges show why this is *not* live (14 calls, latency, cost) — the contrast is the point.
4. **Client interpreter:** compile `lib/dsl/interpret` to run in the browser over the (already-loaded) 14 holdout traces + their labels so tuning is truly instant.

**Test-first:** `alignment` recompute given an edited AST matches the server computation for the same AST (parity test — client and server interpreter agree). **e2e:** open alignment, drag a DSL threshold, assert the agreement number and a flipped-run marker update without a network call.

**Definition of done:** alignment shows agreement + κ + per-judge FP/FN; adjusting a DSL threshold updates the score live with animated verdict flips. Freeze **post-alignment showcase** artifact. Demo-polished. Committed.

---

## Phase 9 — Improvement loop (Screen 6, Gate 3) + honest holdout accounting

**Goal:** misalignment agent proposes typed edits; human reviews/edits/adds recommendations/applies; re-synthesis → re-score → delta. Split/merge reach **back** to the taxonomy (spec §6 — the loop is not linear).

**Tasks**

1. **Misalignment agent** (`lib/agents/misalignment.ts`, Opus, streaming): consumes per holdout disagreement — trace, human verdict+critique, judge verdict+evidence, and for DSL **the full binding trace** (spec §6, so it diagnoses rather than guesses). Emits typed proposals.
2. **Proposal types** (spec §6): `narrow`/`broaden` (LLM prompt), `adjust` (DSL comparison/threshold/accessor), `split`/`merge` (**amend the taxonomy** — reach back to Gate 1), `label_inconsistency` (surface a contradicting human-label pair). Zod-validated payloads.
3. **Screen 6 — Improvement** (`app/improve/page.tsx`): each proposal shows its **motivating disagreements**; a freeform **recommendation box**; actions review/edit/apply. `label_inconsistency` shows the contradicting pair and asks which the user stands by — changing it **updates the label and re-scores** (spec §6: labels are evidence, not infallible truth).
4. **Apply pipeline:** applying a proposal → (for split/merge) mutate taxonomy + re-synthesize affected judges; (for narrow/broaden/adjust) update the judge; then re-run evaluate → new alignment → show **delta**.
5. **Honest holdout accounting** (spec §6): increment `iteration` per re-score; after **3** iterations against the same holdout, show the banner: *"You've tuned against this holdout three times. Label fresh runs to re-establish a clean measurement."* → routes back to `/label`. One conditional; gives the lifecycle its circular ending.

**Test-first:** `label_inconsistency` apply updates the label row and triggers re-score; iteration counter + banner threshold (`>=3`). `split` proposal amends `failure_modes` and re-synthesizes. **Harness (flagged):** misalignment over a known-bad DSL judge proposes an `adjust` citing the binding-trace stale-value pattern (spec §6 example).

**Definition of done:** a disagreement drives a typed proposal; applying it re-scores with a visible delta; the 3-iteration banner fires and links back to labelling. Committed.

---

## Phase 10 — Payoff screen (Screen 7), cost guards & demo hardening

**Goal:** close the loop, protect the deployed demo, and make it presentation-proof.

**Tasks**

1. **Screen 7 — Payoff** (`app/payoff/page.tsx`): run the approved evaluator over the **6 unlabelled runs** (spec §2) — the "it just works on unseen traffic" beat. Show composite verdicts + per-judge firing.
2. **Cost guards** (spec §8): rate-limit session creation per IP; hard-cap improvement iterations at 3; serve **showcase** sessions from cached results rather than re-running agents. Test the cost-bounding conditionals.
3. **Showcase completeness:** ensure all three frozen stages (pre-taxonomy, pre-evaluator, post-alignment) deep-link and render from cache (spec §7 — rescues the demo if wifi/API stalls mid-pitch).
4. **Streaming polish:** every long agent call (cluster/synthesize/misalignment) streams reasoning, never a bare spinner (spec §8).
5. **Full-flow e2e:** Playwright drives runs → label → taxonomy(split) → evaluators → alignment(tune) → improve(apply) → payoff against mocked agents (golden fixtures) for a deterministic CI gate. One live smoke test behind a flag.
6. **Cost & README:** verify per-visitor cost is in the spec's ~$0.70 (worst ~$1.50) envelope (spec §8); write `README.md` (run locally, env vars, deploy, showcase links).

**Definition of done:** the deployed preview runs the entire lifecycle for a fresh visitor and via each showcase link; cost guards active; full-flow e2e green in CI. Tagged as the demo build. Committed and pushed.

---

## Out of scope (spec §10 — do not build)

Live agent execution (traces are pre-baked), auth/accounts, shared cross-visitor corpora, persisting evaluators beyond the session, generated-code judges (the DSL covers the deterministic modes with **no execution surface**).

## Risk register (carried from spec §9, with the mitigation baked into ordering)

| Risk | Where it's retired |
|---|---|
| Seeded critiques must cluster into 4 clean + 1 ambiguous | **Phase 2** — written first, iterated against the live clustering agent, golden-fixtured |
| Judge-synthesis quality unproven until built | **Phase 3** — thin vertical slice is an explicit go/no-go gate before any fan-out |
| Ambiguous cluster must survive as a *designed* artifact | Phase 2 tuning + Phase 6 split UX |
| Live-tuning parity (client vs server interpreter) | Phase 8 parity test |
| Deployed-demo cost blowout | Phase 10 cost guards + cached showcase |

## Suggested milestones

- **M1 (Phases 0–3):** thesis proven for one mode, deployed. The decision point.
- **M2 (Phases 4–7):** full label → ratify → synthesize → approve path with real screens.
- **M3 (Phases 8–10):** alignment + live tuning + improvement loop + payoff, demo-hardened.
