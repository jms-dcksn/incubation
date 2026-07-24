# Human-Driven Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a publicly-deployed demo where a human labels real agent runs, an analysis agent derives a failure taxonomy, the human ratifies it, judges are synthesized per ratified mode, and alignment against held-out human labels drives a human-gated improvement loop.

**Architecture:** Next.js App Router (single deploy on Vercel) with server actions and route handlers for all agent/judge work; Postgres (Neon) via Drizzle holds per-visitor session state keyed by an anonymous cookie; static domain data, 40 pre-baked traces, and 26 seeded critiques ship as committed JSON fixtures. The evaluation core is two testable, deterministic pieces — a zod-validated DSL-judge AST interpreter and an alignment scorer — surrounded by three Anthropic-SDK agents (clustering, synthesis, misalignment) whose outputs pass through human gates before taking effect.

**Tech Stack:** Next.js 15 (App Router, RSC + server actions), TypeScript, Postgres + Drizzle ORM, `@anthropic-ai/sdk`, zod, Tailwind, Vitest for unit tests, Playwright for one smoke test.

## Global Constraints

- **Framework:** Next.js App Router, deployed on Vercel. No separate backend service.
- **Database:** Postgres (Neon) accessed only through Drizzle. No raw SQL in app code except migrations.
- **No auth, no accounts.** Session identity is an anonymous cookie (`hde_session`, httpOnly, SameSite=Lax) mapping to a server-side `sessions` row.
- **No cross-visitor state.** Every session is fully isolated; labels are copied per session, never shared.
- **Models are fixed:** LLM judges use `claude-haiku-4-5` (no thinking). Clustering, synthesis, and misalignment agents use `claude-opus-4-8` with `thinking: {type: "adaptive"}` and `output_config: {effort: "high"}`.
- **DSL judges have no code-execution surface.** The synthesis agent emits an AST as JSON validated by zod; the interpreter walks the AST. Never `eval`, never string-to-code.
- **Composite run verdict:** a run FAILS if any judge fires. Alignment is computed per-judge and overall.
- **The split:** 34 total labelled runs (26 Priya + ~8 visitor). Judge synthesis reads only the 20-run **build set**. Alignment scores only the 14-run **holdout**. 6 runs stay unlabelled for the payoff screen. Taxonomy clustering may read all 34 labels (unsupervised, human-ratified, nothing to leak).
- **Holdout honesty:** after 3 improvement iterations against the same holdout, block further tuning and prompt for fresh labels.
- **Cost guardrails:** rate-limit session creation per IP; cap improvement iterations at 3; serve the showcase session from cached results.
- **Long-running agent calls stream reasoning to the UI**, not a spinner.
- **Build order is prescribed by the spec and is not negotiable:** seeded critiques first (Phase 2), then the thin vertical slice for ONE failure mode end-to-end (Phase 5) before the remaining screens. Screens 2 (Label) and 5 (Alignment) carry the argument — concentrate effort there.

---

## File Structure

```
human-driven-evals/
├── package.json, tsconfig.json, next.config.ts, tailwind.config.ts, vitest.config.ts
├── drizzle.config.ts
├── .env.local.example                      # DATABASE_URL, ANTHROPIC_API_KEY
├── src/
│   ├── db/
│   │   ├── schema.ts                        # Drizzle tables
│   │   ├── client.ts                        # Neon connection
│   │   └── migrations/                      # drizzle-kit output
│   ├── domain/                              # STATIC fixtures + their types (committed)
│   │   ├── types.ts                         # Employee, PolicyClause, Trace, Step, Label
│   │   ├── employees.json                   # ~30 records
│   │   ├── policy.json                      # ~15 clauses
│   │   ├── traces/                          # 40 trace JSON files
│   │   │   └── run-001.json … run-040.json
│   │   ├── seed-labels.json                 # Priya's 26 labels
│   │   ├── split.ts                         # build/holdout/unlabelled run-id partition
│   │   └── index.ts                         # loaders: getTrace, getEmployee, allRuns
│   ├── eval/
│   │   ├── dsl/
│   │   │   ├── ast.ts                        # zod schema for the AST (source of truth)
│   │   │   ├── interpret.ts                  # interpreter + binding trace
│   │   │   └── render.ts                     # AST → human-readable assertion string
│   │   ├── llm-judge.ts                      # single (judge × run) Haiku call
│   │   ├── run-judges.ts                     # composite verdict over a run
│   │   └── scoring.ts                        # agreement %, Cohen's κ, per-judge FP/FN
│   ├── agents/
│   │   ├── anthropic.ts                      # SDK client + model constants + stream helper
│   │   ├── clustering.ts                     # labels → taxonomy proposal
│   │   ├── synthesis.ts                      # ratified mode → judge (llm|dsl)
│   │   └── misalignment.ts                   # disagreements → typed proposals
│   ├── session/
│   │   ├── cookie.ts                         # get/set hde_session
│   │   ├── session.ts                        # getOrCreateSession, rate limit, showcase seed
│   │   └── state.ts                          # typed read/write of session stage + payloads
│   ├── app/
│   │   ├── layout.tsx, page.tsx              # Screen 1: Runs
│   │   ├── label/[runId]/page.tsx            # Screen 2: Label
│   │   ├── taxonomy/page.tsx                 # Screen 3: ratification (Gate 1)
│   │   ├── evaluators/page.tsx               # Screen 4: review (Gate 2)
│   │   ├── alignment/page.tsx                # Screen 5: alignment + live tuning
│   │   ├── improve/page.tsx                  # Screen 6: improvement (Gate 3)
│   │   ├── payoff/page.tsx                   # Screen 7: unlabelled runs
│   │   ├── actions/                          # server actions (label, ratify, synthesize, …)
│   │   └── api/agents/[agent]/route.ts       # SSE streaming endpoints
│   └── components/                           # TracePane, LabelForm, ClusterCard, JudgeCard,
│                                             #   AlignmentHeadline, DisagreementList, BindingTrace…
├── scripts/
│   └── critique-harness.ts                   # runs clustering over seed-labels for iteration
└── tests/                                    # Vitest unit tests mirror src/ paths
```

---

## Phase 0 — Project scaffold and infrastructure

### Task 0.1: Next.js + TypeScript + Tailwind + Vitest scaffold

**Files:**
- Create: `human-driven-evals/package.json`, `tsconfig.json`, `next.config.ts`, `tailwind.config.ts`, `postcss.config.mjs`, `vitest.config.ts`, `src/app/layout.tsx`, `src/app/page.tsx`, `src/app/globals.css`
- Test: `tests/smoke.test.ts`

**Interfaces:**
- Produces: a runnable `next dev` app and a working `vitest` runner for every later task.

- [ ] **Step 1: Write the failing test**
```ts
// tests/smoke.test.ts
import { expect, test } from "vitest";
test("test runner works", () => {
  expect(1 + 1).toBe(2);
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd human-driven-evals && npx vitest run`
Expected: fails — `vitest` is not installed / no config found.

- [ ] **Step 3: Write minimal implementation**
Scaffold with `create-next-app` non-interactively, then add Vitest:
```bash
cd human-driven-evals
npx create-next-app@latest . --ts --tailwind --app --src-dir --no-eslint --use-npm --import-alias "@/*"
npm i -D vitest @vitejs/plugin-react jsdom
```
```ts
// vitest.config.ts
import { defineConfig } from "vitest/config";
export default defineConfig({
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
});
```
Add to `package.json` scripts: `"test": "vitest run"`, `"test:watch": "vitest"`.

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Scaffold Next.js app with Tailwind and Vitest"
```

### Task 0.2: Drizzle + Neon connection and schema

**Files:**
- Create: `src/db/schema.ts`, `src/db/client.ts`, `drizzle.config.ts`, `.env.local.example`
- Test: `tests/db/schema.test.ts`

**Interfaces:**
- Produces: `sessions`, `labels`, `taxonomyModes`, `judges`, `judgeResults`, `iterations` tables; `db` client.

- [ ] **Step 1: Write the failing test**
```ts
// tests/db/schema.test.ts
import { expect, test } from "vitest";
import * as schema from "@/db/schema";
test("all required tables are defined", () => {
  for (const t of ["sessions","labels","taxonomyModes","judges","judgeResults","iterations"])
    expect(schema).toHaveProperty(t);
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/db/schema.test.ts`
Expected: fails — `@/db/schema` does not exist.

- [ ] **Step 3: Write minimal implementation**
```ts
// src/db/schema.ts
import { pgTable, uuid, text, timestamp, integer, jsonb, boolean, index } from "drizzle-orm/pg-core";

export const sessions = pgTable("sessions", {
  id: uuid("id").defaultRandom().primaryKey(),
  cookieKey: text("cookie_key").notNull().unique(),
  stage: text("stage").notNull().default("labelling"), // labelling|taxonomy|evaluators|alignment|improve|payoff
  iterationCount: integer("iteration_count").notNull().default(0),
  isShowcase: boolean("is_showcase").notNull().default(false),
  createdAt: timestamp("created_at").defaultNow().notNull(),
}, (t) => ({ cookieIdx: index("sessions_cookie_idx").on(t.cookieKey) }));

export const labels = pgTable("labels", {
  id: uuid("id").defaultRandom().primaryKey(),
  sessionId: uuid("session_id").notNull().references(() => sessions.id),
  runId: text("run_id").notNull(),
  verdict: text("verdict").notNull(), // pass|fail
  critique: text("critique").notNull().default(""),
  author: text("author").notNull(), // priya|visitor
  createdAt: timestamp("created_at").defaultNow().notNull(),
}, (t) => ({ sessIdx: index("labels_session_idx").on(t.sessionId) }));

// modes: one ratified failure mode. `sourceProposalId` links back to a clustering proposal.
export const taxonomyModes = pgTable("taxonomy_modes", {
  id: uuid("id").defaultRandom().primaryKey(),
  sessionId: uuid("session_id").notNull().references(() => sessions.id),
  name: text("name").notNull(),
  description: text("description").notNull().default(""),
  memberRunIds: jsonb("member_run_ids").$type<string[]>().notNull().default([]),
  ratified: boolean("ratified").notNull().default(false),
});

// judges: one per ratified mode. spec is either an LLM prompt or a DSL AST.
export const judges = pgTable("judges", {
  id: uuid("id").defaultRandom().primaryKey(),
  sessionId: uuid("session_id").notNull().references(() => sessions.id),
  modeId: uuid("mode_id").notNull().references(() => taxonomyModes.id),
  type: text("type").notNull(), // llm|dsl
  spec: jsonb("spec").$type<unknown>().notNull(), // {prompt} for llm, AST for dsl
  approved: boolean("approved").notNull().default(false),
  version: integer("version").notNull().default(1),
});

export const judgeResults = pgTable("judge_results", {
  id: uuid("id").defaultRandom().primaryKey(),
  sessionId: uuid("session_id").notNull().references(() => sessions.id),
  judgeId: uuid("judge_id").notNull().references(() => judges.id),
  runId: text("run_id").notNull(),
  fired: boolean("fired").notNull(),          // true = judge says this mode is present (a failure)
  evidence: jsonb("evidence").$type<unknown>(), // {span, confidence} for llm; binding trace for dsl
  iteration: integer("iteration").notNull().default(0),
});

export const iterations = pgTable("iterations", {
  id: uuid("id").defaultRandom().primaryKey(),
  sessionId: uuid("session_id").notNull().references(() => sessions.id),
  n: integer("n").notNull(),
  alignment: jsonb("alignment").$type<unknown>().notNull(), // scoring snapshot
  createdAt: timestamp("created_at").defaultNow().notNull(),
});
```
```ts
// src/db/client.ts
import { drizzle } from "drizzle-orm/neon-http";
import { neon } from "@neondatabase/serverless";
import * as schema from "./schema";
const sql = neon(process.env.DATABASE_URL!);
export const db = drizzle(sql, { schema });
```
```ts
// drizzle.config.ts
import type { Config } from "drizzle-kit";
export default { schema: "./src/db/schema.ts", out: "./src/db/migrations",
  dialect: "postgresql", dbCredentials: { url: process.env.DATABASE_URL! } } satisfies Config;
```
Install: `npm i drizzle-orm @neondatabase/serverless && npm i -D drizzle-kit`.
Add `.env.local.example` with `DATABASE_URL=` and `ANTHROPIC_API_KEY=`.

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/db/schema.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add Drizzle schema and Neon client"
```

### Task 0.3: Generate and apply the initial migration

**Files:**
- Create: `src/db/migrations/0000_*.sql` (generated)

- [ ] **Step 1:** Run `npx drizzle-kit generate` — verify a migration SQL file appears containing all six tables.
- [ ] **Step 2:** With a Neon `DATABASE_URL` set in `.env.local`, run `npx drizzle-kit migrate`. Expected: applies cleanly.
- [ ] **Step 3: Commit**
```bash
git add -A && git commit -m "Generate initial Drizzle migration"
```

---

## Phase 1 — Domain types and static data loaders

### Task 1.1: Domain and trace type definitions

**Files:**
- Create: `src/domain/types.ts`
- Test: `tests/domain/types.test.ts`

**Interfaces:**
- Produces: `Employee`, `PolicyClause`, `Step` (discriminated union), `Trace`, `Label`, `Verdict`.

- [ ] **Step 1: Write the failing test**
```ts
// tests/domain/types.test.ts
import { expect, test } from "vitest";
import { TraceSchema } from "@/domain/types";
test("a well-formed trace parses", () => {
  const t = {
    runId: "run-001",
    userQuery: "How many leave days do I have left?",
    employeeName: "Ada Chen",
    steps: [
      { kind: "tool_call", tool: "lookup_employee", args: { name: "Ada Chen" } },
      { kind: "tool_result", tool: "lookup_employee", ok: true, result: { days_remaining: 14 } },
      { kind: "final_answer", text: "You have 12 days left.", fields: { stated_days: 12 } },
    ],
  };
  expect(() => TraceSchema.parse(t)).not.toThrow();
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/domain/types.test.ts`
Expected: fails — `@/domain/types` missing.

- [ ] **Step 3: Write minimal implementation**
```ts
// src/domain/types.ts
import { z } from "zod";

export const VerdictSchema = z.enum(["pass", "fail"]);
export type Verdict = z.infer<typeof VerdictSchema>;

export const EmployeeSchema = z.object({
  name: z.string(), tenureMonths: z.number(), location: z.string(),
  employmentType: z.enum(["full_time", "part_time", "contractor"]),
  accruedLeave: z.number(), remainingBalance: z.number(),
});
export type Employee = z.infer<typeof EmployeeSchema>;

export const PolicyClauseSchema = z.object({
  id: z.string(), title: z.string(), text: z.string(),
  jurisdiction: z.string().optional(),
});
export type PolicyClause = z.infer<typeof PolicyClauseSchema>;

// Step kinds are what the DSL accessor selects against — keep them stable.
export const StepSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("tool_call"), tool: z.string(), args: z.record(z.unknown()) }),
  z.object({ kind: z.literal("tool_result"), tool: z.string(), ok: z.boolean(),
             result: z.record(z.unknown()).optional(), error: z.string().optional() }),
  z.object({ kind: z.literal("assistant"), text: z.string() }),
  z.object({ kind: z.literal("final_answer"), text: z.string(),
             fields: z.record(z.unknown()).default({}) }),
]);
export type Step = z.infer<typeof StepSchema>;

export const TraceSchema = z.object({
  runId: z.string(), userQuery: z.string(), employeeName: z.string(),
  steps: z.array(StepSchema),
});
export type Trace = z.infer<typeof TraceSchema>;

export const LabelSchema = z.object({
  runId: z.string(), verdict: VerdictSchema,
  critique: z.string(), author: z.enum(["priya", "visitor"]),
});
export type Label = z.infer<typeof LabelSchema>;
```

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/domain/types.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add domain and trace type schemas"
```

### Task 1.2: Static data — employees, policy, and the run split

**Files:**
- Create: `src/domain/employees.json`, `src/domain/policy.json`, `src/domain/split.ts`, `src/domain/index.ts`
- Test: `tests/domain/loaders.test.ts`

**Interfaces:**
- Produces: `getEmployee(name)`, `getPolicyClause(id)`, `allRunIds()`, `BUILD_SET`, `HOLDOUT`, `UNLABELLED`.

- [ ] **Step 1: Write the failing test**
```ts
// tests/domain/loaders.test.ts
import { expect, test } from "vitest";
import { BUILD_SET, HOLDOUT, UNLABELLED } from "@/domain/split";
import { getEmployee } from "@/domain/index";
test("split is 20 / 14 / 6, disjoint", () => {
  expect(BUILD_SET.length).toBe(20);
  expect(HOLDOUT.length).toBe(14);
  expect(UNLABELLED.length).toBe(6);
  const all = new Set([...BUILD_SET, ...HOLDOUT, ...UNLABELLED]);
  expect(all.size).toBe(40);
});
test("employees load and parse", () => {
  expect(getEmployee("Ada Chen")).toBeTruthy();
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/domain/loaders.test.ts`
Expected: fails — modules missing.

- [ ] **Step 3: Write minimal implementation**
Author `employees.json` (~30 records) and `policy.json` (~15 clauses; **must include** clauses on parental leave, carry-over caps, jurisdiction-specific entitlements, notice periods — the fixture for planted Mode 1 fabrications). Then:
```ts
// src/domain/split.ts
// Partition is fixed and committed so every session sees the same slices.
export const BUILD_SET  = Array.from({length:20},(_,i)=>`run-${String(i+1).padStart(3,"0")}`);
export const HOLDOUT    = Array.from({length:14},(_,i)=>`run-${String(i+21).padStart(3,"0")}`);
export const UNLABELLED = Array.from({length:6}, (_,i)=>`run-${String(i+35).padStart(3,"0")}`);
```
```ts
// src/domain/index.ts
import employeesRaw from "./employees.json";
import policyRaw from "./policy.json";
import { EmployeeSchema, PolicyClauseSchema, TraceSchema, type Trace } from "./types";
const employees = employeesRaw.map((e) => EmployeeSchema.parse(e));
const policy = policyRaw.map((c) => PolicyClauseSchema.parse(c));
export const getEmployee = (name: string) => employees.find((e) => e.name === name);
export const getPolicyClause = (id: string) => policy.find((c) => c.id === id);
export const allEmployees = () => employees;
export const allPolicy = () => policy;
export async function getTrace(runId: string): Promise<Trace> {
  const raw = (await import(`./traces/${runId}.json`)).default;
  return TraceSchema.parse(raw);
}
```

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/domain/loaders.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add static employee/policy data and run split"
```

### Task 1.3: Author the 40 traces with planted failure modes

**Files:**
- Create: `src/domain/traces/run-001.json` … `run-040.json`
- Test: `tests/domain/traces.test.ts`

**Interfaces:**
- Produces: 40 committed traces. ~35% (14 runs) exhibit ≥1 of the five planted failure modes; each mode appears across multiple runs. Modes 3 (arithmetic) and 4 (swallowed tool error) must be deterministically checkable from step fields.

- [ ] **Step 1: Write the failing test**
```ts
// tests/domain/traces.test.ts
import { expect, test } from "vitest";
import { TraceSchema } from "@/domain/types";
const ids = Array.from({length:40},(_,i)=>`run-${String(i+1).padStart(3,"0")}`);
test.each(ids)("%s is a valid trace", async (id) => {
  const raw = (await import(`@/domain/traces/${id}.json`)).default;
  expect(() => TraceSchema.parse(raw)).not.toThrow();
});
test("at least one run has a swallowed tool error (Mode 4)", async () => {
  let found = false;
  for (const id of ids) {
    const t = TraceSchema.parse((await import(`@/domain/traces/${id}.json`)).default);
    const errored = t.steps.some((s) => s.kind === "tool_result" && s.ok === false);
    const answered = t.steps.some((s) => s.kind === "final_answer");
    if (errored && answered) found = true;
  }
  expect(found).toBe(true);
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/domain/traces.test.ts`
Expected: fails — trace files missing.

- [ ] **Step 3: Write minimal implementation**
Hand-author 40 traces. Distribute planted modes so each appears in ≥3 runs and totals ~14 failing runs:
  - **Mode 3 (arithmetic):** `tool_result.result.days_remaining` ≠ `final_answer.fields.stated_days`. Deterministically checkable.
  - **Mode 4 (swallowed tool error):** a `tool_result` with `ok:false` + `error`, followed by a confident `final_answer`. Deterministically checkable.
  - **Mode 1 (fabricated clause):** `final_answer.text` cites a clause id/title absent from `policy.json`.
  - **Mode 2 (wrong employee):** `lookup_employee` args name ≠ `employeeName`, or the answer uses another record's numbers.
  - **Mode 5 (premature closure):** `final_answer.text` says "you're all set" without addressing `userQuery`.
Keep passing runs realistic (correct lookups, correct arithmetic, cited real clauses).

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/domain/traces.test.ts`
Expected: PASS (42 assertions).

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Author 40 pre-baked traces with planted failure modes"
```

---

## Phase 2 — Seeded critiques (highest-risk asset; build first)

### Task 2.1: Author Priya's 26 seeded labels + critiques

**Files:**
- Create: `src/domain/seed-labels.json`
- Test: `tests/domain/seed-labels.test.ts`

**Interfaces:**
- Produces: 26 `Label` objects (`author:"priya"`) covering the build+holdout runs, clustering into four clean groups plus one deliberately ambiguous group (Modes 1 & 2 phrased as "it told me something untrue about my leave").

- [ ] **Step 1: Write the failing test**
```ts
// tests/domain/seed-labels.test.ts
import { expect, test } from "vitest";
import seed from "@/domain/seed-labels.json";
import { LabelSchema } from "@/domain/types";
test("26 valid priya labels, each critique non-trivial", () => {
  expect(seed.length).toBe(26);
  for (const l of seed) {
    const p = LabelSchema.parse(l);
    expect(p.author).toBe("priya");
    if (p.verdict === "fail") expect(p.critique.trim().length).toBeGreaterThan(20);
  }
});
test("fail labels vary in length (human-sounding, not templated)", () => {
  const lens = seed.filter((l) => l.verdict === "fail").map((l) => l.critique.length);
  expect(Math.max(...lens) - Math.min(...lens)).toBeGreaterThan(40);
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/domain/seed-labels.test.ts`
Expected: fails — `seed-labels.json` missing.

- [ ] **Step 3: Write minimal implementation**
Author 26 labels. Write critiques as a QA lead would: varied phrasing/length, some terse, some detailed. Deliberately phrase Mode 1 and Mode 2 failures ambiguously ("it quoted a policy that doesn't seem right for me", "the days it gave me were just wrong") so clustering lumps them and a human must split them at Gate 1. Keep four other clusters (arithmetic, swallowed error, premature closure, plus genuine passes) clean and separable.

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/domain/seed-labels.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Author 26 seeded critiques with one designed ambiguity"
```

> **Iteration note:** Task 5.1 (clustering agent) and Task 2.2 form a loop. Expect to revise this file after seeing real clustering output. Do not treat these critiques as final until Task 5.2 confirms the ambiguous cluster behaves as designed.

### Task 2.2: Critique iteration harness

**Files:**
- Create: `scripts/critique-harness.ts`

**Interfaces:**
- Produces: a CLI that runs the clustering agent (Task 5.1) over `seed-labels.json` and prints proposed clusters + members, so critiques can be tuned against real output. (Implement the thin version after Task 5.1 exists; stub the import now.)

- [ ] **Step 1:** Write `scripts/critique-harness.ts` that imports `clusterLabels` (Phase 5), loads `seed-labels.json`, runs it, and pretty-prints each proposed cluster with member run-ids and critiques.
- [ ] **Step 2:** Add npm script `"critique:harness": "tsx scripts/critique-harness.ts"`.
- [ ] **Step 3: Commit**
```bash
git add -A && git commit -m "Add critique iteration harness (wired in Phase 5)"
```

---

## Phase 3 — DSL judge engine (deterministic core)

### Task 3.1: DSL AST zod schema

**Files:**
- Create: `src/eval/dsl/ast.ts`
- Test: `tests/eval/dsl/ast.test.ts`

**Interfaces:**
- Produces: `NodeSchema`, `type Node`. Node kinds: `accessor`, `literal`, `compare`, `exists`, `notExists`, `and`, `or`, `not`, `contains`.

- [ ] **Step 1: Write the failing test**
```ts
// tests/eval/dsl/ast.test.ts
import { expect, test } from "vitest";
import { NodeSchema } from "@/eval/dsl/ast";
test("the spec's example AST validates", () => {
  const ast = { op: "compare", cmp: "eq",
    left:  { op: "accessor", step: { kind: "tool_result", tool: "leave_balance" }, path: "days_remaining" },
    right: { op: "accessor", step: { kind: "final_answer" }, path: "stated_days" } };
  expect(() => NodeSchema.parse(ast)).not.toThrow();
});
test("unknown op is rejected", () => {
  expect(() => NodeSchema.parse({ op: "exec", cmd: "rm -rf" })).toThrow();
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/eval/dsl/ast.test.ts`
Expected: fails — schema missing.

- [ ] **Step 3: Write minimal implementation**
```ts
// src/eval/dsl/ast.ts
import { z } from "zod";

const StepSelector = z.object({
  kind: z.enum(["tool_call", "tool_result", "assistant", "final_answer"]),
  tool: z.string().optional(),       // required to disambiguate when multiple tools
  index: z.number().int().optional(), // optional explicit step index; else first match
});

// Recursive union — declare with z.lazy.
export type Node =
  | { op: "accessor"; step: z.infer<typeof StepSelector>; path: string }
  | { op: "literal"; value: unknown; tolerance?: number }
  | { op: "compare"; cmp: "eq"|"neq"|"gt"|"lt"|"gte"|"lte"; left: Node; right: Node }
  | { op: "exists"; of: Node } | { op: "notExists"; of: Node }
  | { op: "and"; nodes: Node[] } | { op: "or"; nodes: Node[] } | { op: "not"; of: Node }
  | { op: "contains"; haystack: Node; needle: Node };

export const NodeSchema: z.ZodType<Node> = z.lazy(() =>
  z.discriminatedUnion("op", [
    z.object({ op: z.literal("accessor"), step: StepSelector, path: z.string() }),
    z.object({ op: z.literal("literal"), value: z.unknown(), tolerance: z.number().optional() }),
    z.object({ op: z.literal("compare"), cmp: z.enum(["eq","neq","gt","lt","gte","lte"]),
               left: NodeSchema, right: NodeSchema }),
    z.object({ op: z.literal("exists"), of: NodeSchema }),
    z.object({ op: z.literal("notExists"), of: NodeSchema }),
    z.object({ op: z.literal("and"), nodes: z.array(NodeSchema) }),
    z.object({ op: z.literal("or"), nodes: z.array(NodeSchema) }),
    z.object({ op: z.literal("not"), of: NodeSchema }),
    z.object({ op: z.literal("contains"), haystack: NodeSchema, needle: NodeSchema }),
  ]) as unknown as z.ZodType<Node>);
```

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/eval/dsl/ast.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add zod-validated DSL AST schema"
```

### Task 3.2: DSL interpreter with binding trace

**Files:**
- Create: `src/eval/dsl/interpret.ts`
- Test: `tests/eval/dsl/interpret.test.ts`

**Interfaces:**
- Consumes: `Node` (Task 3.1), `Trace` (Task 1.1).
- Produces: `evaluate(node, trace): { fired: boolean; bindings: Binding[] }` where a **root that evaluates truthy means the failure mode is present (judge fires)**. `Binding = { path: string; value: unknown; stepIndex: number|null; }`.

- [ ] **Step 1: Write the failing test**
```ts
// tests/eval/dsl/interpret.test.ts
import { expect, test } from "vitest";
import { evaluate } from "@/eval/dsl/interpret";
import type { Trace } from "@/domain/types";
import type { Node } from "@/eval/dsl/ast";

const trace: Trace = { runId:"t", userQuery:"q", employeeName:"Ada Chen", steps:[
  { kind:"tool_call", tool:"leave_balance", args:{ name:"Ada Chen" } },
  { kind:"tool_result", tool:"leave_balance", ok:true, result:{ days_remaining:14 } },
  { kind:"final_answer", text:"12 days", fields:{ stated_days:12 } },
]};

// Mode 3 judge: fires when stated_days != days_remaining (arithmetic mismatch).
const mode3: Node = { op:"not", of:{ op:"compare", cmp:"eq",
  left:{ op:"accessor", step:{ kind:"tool_result", tool:"leave_balance" }, path:"days_remaining" },
  right:{ op:"accessor", step:{ kind:"final_answer" }, path:"stated_days" } } };

test("fires on arithmetic mismatch and records bindings", () => {
  const r = evaluate(mode3, trace);
  expect(r.fired).toBe(true);
  expect(r.bindings).toContainEqual({ path:"days_remaining", value:14, stepIndex:1 });
  expect(r.bindings).toContainEqual({ path:"stated_days", value:12, stepIndex:2 });
});

test("tolerance suppresses near-equal numbers", () => {
  const withTol: Node = { op:"compare", cmp:"eq",
    left:{ op:"literal", value:14, tolerance:3 },
    right:{ op:"accessor", step:{ kind:"final_answer" }, path:"stated_days" } };
  expect(evaluate(withTol, trace).fired).toBe(true); // |14-12| <= 3
});

// Mode 4 judge: a tool_result with ok=false exists AND a final_answer exists.
test("swallowed tool error via exists composition", () => {
  const errTrace: Trace = { ...trace, steps:[
    { kind:"tool_result", tool:"lookup_employee", ok:false, error:"not found" },
    { kind:"final_answer", text:"You have 10 days", fields:{ stated_days:10 } },
  ]};
  const mode4: Node = { op:"and", nodes:[
    { op:"exists", of:{ op:"accessor", step:{ kind:"tool_result" }, path:"error" } },
    { op:"exists", of:{ op:"accessor", step:{ kind:"final_answer" }, path:"text" } },
  ]};
  expect(evaluate(mode4, errTrace).fired).toBe(true);
  expect(evaluate(mode4, trace).fired).toBe(false); // no error in the clean trace
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/eval/dsl/interpret.test.ts`
Expected: fails — `evaluate` missing.

- [ ] **Step 3: Write minimal implementation**
```ts
// src/eval/dsl/interpret.ts
import type { Trace } from "@/domain/types";
import type { Node } from "./ast";

export type Binding = { path: string; value: unknown; stepIndex: number | null };
type EvalResult = { value: unknown; bindings: Binding[] };

function resolveStep(trace: Trace, sel: Node & { op: "accessor" } extends never ? never : any) {
  const { kind, tool, index } = sel.step;
  const matches = trace.steps
    .map((s, i) => ({ s, i }))
    .filter(({ s }) => s.kind === kind && (tool === undefined || (s as any).tool === tool));
  if (matches.length === 0) return { step: null, index: null as number | null };
  const chosen = index !== undefined
    ? matches.find(({ i }) => i === index) ?? null
    : matches[0];
  return chosen ? { step: chosen.s, index: chosen.i } : { step: null, index: null };
}

function getPath(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, k) =>
    acc && typeof acc === "object" ? (acc as any)[k] : undefined, obj);
}

function ev(node: Node, trace: Trace, acc: Binding[]): EvalResult {
  switch (node.op) {
    case "literal":
      return { value: node.value, bindings: [] };
    case "accessor": {
      const { step, index } = resolveStep(trace, node);
      // accessor reads from the step object's payload (result/fields/args/text/error live at top level)
      const source = step ? { ...(step as any).result, ...(step as any).fields, ...(step as any) } : undefined;
      const value = source === undefined ? undefined : getPath(source, node.path);
      const b: Binding = { path: node.path, value, stepIndex: index };
      acc.push(b);
      return { value, bindings: [b] };
    }
    case "exists":   return { value: ev(node.of, trace, acc).value !== undefined, bindings: [] };
    case "notExists":return { value: ev(node.of, trace, acc).value === undefined, bindings: [] };
    case "not":      return { value: !truthy(ev(node.of, trace, acc).value), bindings: [] };
    case "and":      return { value: node.nodes.every((n) => truthy(ev(n, trace, acc).value)), bindings: [] };
    case "or":       return { value: node.nodes.some((n) => truthy(ev(n, trace, acc).value)), bindings: [] };
    case "contains": {
      const h = ev(node.haystack, trace, acc).value;
      const n = ev(node.needle, trace, acc).value;
      if (typeof h === "string") return { value: h.includes(String(n)), bindings: [] };
      if (Array.isArray(h))      return { value: h.includes(n), bindings: [] };
      return { value: false, bindings: [] };
    }
    case "compare": {
      const l = ev(node.left, trace, acc);
      const r = ev(node.right, trace, acc);
      // tolerance may live on either literal operand
      const tol = (node.left.op === "literal" ? node.left.tolerance : undefined)
               ?? (node.right.op === "literal" ? node.right.tolerance : undefined);
      return { value: cmp(node.cmp, l.value, r.value, tol), bindings: [] };
    }
  }
}

function truthy(v: unknown): boolean { return v === true; }

function cmp(op: string, a: unknown, b: unknown, tol?: number): boolean {
  const na = Number(a), nb = Number(b);
  const numeric = !Number.isNaN(na) && !Number.isNaN(nb);
  switch (op) {
    case "eq":  return numeric && tol !== undefined ? Math.abs(na - nb) <= tol : a === b;
    case "neq": return numeric && tol !== undefined ? Math.abs(na - nb) > tol : a !== b;
    case "gt":  return na > nb;   case "lt":  return na < nb;
    case "gte": return na >= nb;  case "lte": return na <= nb;
    default: return false;
  }
}

export function evaluate(root: Node, trace: Trace): { fired: boolean; bindings: Binding[] } {
  const bindings: Binding[] = [];
  const { value } = ev(root, trace, bindings);
  return { fired: truthy(value), bindings };
}
```
> Note: `compare` returns a boolean but is often the root; `truthy` treats only `true` as firing, so wrap comparisons that should fire-on-true directly, or in `not`/`and` as the tests show. Keep the semantic **"root truthy ⇒ mode present ⇒ fail"** consistent across all synthesized judges (Phase 5 synthesis prompt states this explicitly).

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/eval/dsl/interpret.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add DSL interpreter with binding trace"
```

### Task 3.3: AST → human-readable assertion renderer

**Files:**
- Create: `src/eval/dsl/render.ts`
- Test: `tests/eval/dsl/render.test.ts`

**Interfaces:**
- Consumes: `Node`, and optionally `Binding[]` from a run.
- Produces: `renderAssertion(node, bindings?)` → string like `leave_balance.days_remaining ⟨14⟩ == final_answer.stated_days ⟨12⟩ ✗`, plus `leafRefs(node)` mapping each accessor leaf to its step for click-to-scroll in the UI.

- [ ] **Step 1: Write the failing test**
```ts
// tests/eval/dsl/render.test.ts
import { expect, test } from "vitest";
import { renderAssertion } from "@/eval/dsl/render";
import type { Node } from "@/eval/dsl/ast";
test("renders compare with inline bound values", () => {
  const n: Node = { op:"compare", cmp:"eq",
    left:{ op:"accessor", step:{ kind:"tool_result", tool:"leave_balance" }, path:"days_remaining" },
    right:{ op:"accessor", step:{ kind:"final_answer" }, path:"stated_days" } };
  const s = renderAssertion(n, [
    { path:"days_remaining", value:14, stepIndex:1 },
    { path:"stated_days", value:12, stepIndex:2 },
  ]);
  expect(s).toContain("days_remaining");
  expect(s).toContain("⟨14⟩");
  expect(s).toContain("⟨12⟩");
  expect(s).toContain("==");
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/eval/dsl/render.test.ts`
Expected: fails — module missing.

- [ ] **Step 3: Write minimal implementation** — recursive stringifier: `accessor` → `` `${tool??kind}.${path}` `` plus ⟨value⟩ if a matching binding exists; `compare` → `left <sym> right`; `and/or/not` → parenthesised; symbols map `eq→==,neq→!=,gt→>,…`. Add `leafRefs(node)` returning `{path, stepIndex}[]`.

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/eval/dsl/render.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add DSL assertion renderer"
```

---

## Phase 4 — Alignment scoring (deterministic core)

### Task 4.1: Agreement, Cohen's κ, per-judge FP/FN

**Files:**
- Create: `src/eval/scoring.ts`
- Test: `tests/eval/scoring.test.ts`

**Interfaces:**
- Consumes: per-run human verdicts and composite/per-judge machine verdicts over the holdout.
- Produces: `score({ human, machine }): { agreement, kappa, n }` and `perJudge(runs): Record<judgeId,{fp,fn,tp,tn}>`. Composite machine verdict = `fail` if any judge fires.

- [ ] **Step 1: Write the failing test**
```ts
// tests/eval/scoring.test.ts
import { expect, test } from "vitest";
import { score, cohensKappa } from "@/eval/scoring";
test("perfect agreement", () => {
  const r = score({ human:["fail","pass","fail"], machine:["fail","pass","fail"] });
  expect(r.agreement).toBe(1); expect(r.kappa).toBe(1);
});
test("always-pass judge is exposed by kappa", () => {
  // 65% base rate pass: agreement looks OK, kappa ~ 0
  const human   = ["pass","pass","pass","pass","pass","pass","fail","fail","fail","fail"];
  const machine = Array(10).fill("pass") as ("pass"|"fail")[];
  const r = score({ human, machine });
  expect(r.agreement).toBeCloseTo(0.6, 5);
  expect(r.kappa).toBeCloseTo(0, 5); // degenerate — the guard the spec asks for
});
test("kappa handles the no-variance edge without NaN", () => {
  expect(cohensKappa(["pass","pass"], ["pass","pass"])).toBe(1);
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `npx vitest run tests/eval/scoring.test.ts`
Expected: fails — module missing.

- [ ] **Step 3: Write minimal implementation**
```ts
// src/eval/scoring.ts
type V = "pass" | "fail";
export function cohensKappa(a: V[], b: V[]): number {
  const n = a.length; if (n === 0) return 0;
  let po = 0; for (let i=0;i<n;i++) if (a[i]===b[i]) po++; po/=n;
  const pa = a.filter(v=>v==="fail").length/n, pb = b.filter(v=>v==="fail").length/n;
  const pe = pa*pb + (1-pa)*(1-pb);
  if (pe === 1) return po === 1 ? 1 : 0; // no variance
  return (po - pe) / (1 - pe);
}
export function score({ human, machine }: { human: V[]; machine: V[] }) {
  const n = human.length;
  const agreement = n ? human.filter((h,i)=>h===machine[i]).length / n : 0;
  return { agreement, kappa: cohensKappa(human, machine), n };
}
export function perJudge(runs: { human: V; fired: boolean }[]) {
  // "fired" = judge asserts failure. FP = fired but human passed; FN = didn't fire but human failed.
  let fp=0,fn=0,tp=0,tn=0;
  for (const { human, fired } of runs) {
    if (fired && human==="fail") tp++;
    else if (fired && human==="pass") fp++;
    else if (!fired && human==="fail") fn++;
    else tn++;
  }
  return { fp, fn, tp, tn };
}
```

- [ ] **Step 4: Run test to verify it passes**
Run: `npx vitest run tests/eval/scoring.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add alignment scoring with Cohen's kappa"
```

### Task 4.2: Composite judge runner

**Files:**
- Create: `src/eval/run-judges.ts`
- Test: `tests/eval/run-judges.test.ts`

**Interfaces:**
- Consumes: a set of judges (`{id,type,spec}`), a run's `Trace`.
- Produces: `runJudgesOnTrace(judges, trace)` → `{ composite: V; perJudge: {judgeId, fired, evidence}[] }`. DSL judges evaluate synchronously via `evaluate`; LLM judges via `callLlmJudge` (Phase 6, injected). Composite = fail if any fired.

- [ ] **Step 1: Write the failing test** — build two DSL judges (Mode 3, Mode 4) and assert composite=`fail` when either fires, `pass` when neither does; assert `perJudge` carries the binding trace as evidence for DSL judges.
- [ ] **Step 2:** Run `npx vitest run tests/eval/run-judges.test.ts` → fails.
- [ ] **Step 3:** Implement `runJudgesOnTrace`; branch on `judge.type`: `dsl` → `evaluate(NodeSchema.parse(judge.spec), trace)`; `llm` → `await callLlmJudge(judge.spec, trace)` (accept the LLM caller as a parameter so tests inject a fake).
- [ ] **Step 4:** Run test → PASS.
- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add composite judge runner"
```

---

## Phase 5 — Agents and the thin vertical slice

### Task 5.1: Anthropic client + clustering agent

**Files:**
- Create: `src/agents/anthropic.ts`, `src/agents/clustering.ts`
- Test: `tests/agents/clustering.test.ts`

**Interfaces:**
- Produces: `getClient()`, model constants `HAIKU`, `OPUS`, `streamOpus(...)`; `clusterLabels(labels): Promise<ClusterProposal[]>` where `ClusterProposal = { name, description, memberRunIds, exemplarCritiques }`. Uses `claude-opus-4-8`, `thinking:{type:"adaptive"}`, `output_config:{effort:"high"}`, and **tool-use with a zod-validated schema** to force structured output.

- [ ] **Step 1: Write the failing test** (mock the SDK)
```ts
// tests/agents/clustering.test.ts
import { expect, test, vi } from "vitest";
vi.mock("@/agents/anthropic", () => ({
  HAIKU:"claude-haiku-4-5", OPUS:"claude-opus-4-8",
  getClient: () => ({ messages: { create: async () => ({
    content: [{ type:"tool_use", name:"emit_clusters", input:{ clusters:[
      { name:"Untrue leave info", description:"...", memberRunIds:["run-003","run-007"], exemplarCritiques:["wrong days"] },
    ]}}]
  })}}),
}));
import { clusterLabels } from "@/agents/clustering";
test("returns validated cluster proposals", async () => {
  const out = await clusterLabels([
    { runId:"run-003", verdict:"fail", critique:"the days it gave me were just wrong", author:"priya" },
  ]);
  expect(out[0].name).toBe("Untrue leave info");
  expect(out[0].memberRunIds).toContain("run-003");
});
```

- [ ] **Step 2:** Run `npx vitest run tests/agents/clustering.test.ts` → fails.
- [ ] **Step 3: Write minimal implementation**
```ts
// src/agents/anthropic.ts
import Anthropic from "@anthropic-ai/sdk";
export const HAIKU = "claude-haiku-4-5";
export const OPUS  = "claude-opus-4-8";
let _c: Anthropic | null = null;
export const getClient = () => (_c ??= new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY! }));
```
```ts
// src/agents/clustering.ts
import { z } from "zod";
import { getClient, OPUS } from "./anthropic";
import type { Label } from "@/domain/types";

export const ClusterProposalSchema = z.object({
  name: z.string(), description: z.string(),
  memberRunIds: z.array(z.string()), exemplarCritiques: z.array(z.string()),
});
export type ClusterProposal = z.infer<typeof ClusterProposalSchema>;

const SYSTEM = `You are a QA analyst deriving a failure taxonomy from human critiques of an
HR leave-assistant agent. Group the FAIL labels into coherent failure modes based only on what
the critiques say. Do not invent modes not evidenced by critiques. Prefer fewer, well-supported
clusters. Emit clusters via the emit_clusters tool.`;

const TOOL = { name:"emit_clusters", description:"Return the proposed failure-mode clusters.",
  input_schema:{ type:"object", properties:{ clusters:{ type:"array", items:{ type:"object",
    properties:{ name:{type:"string"}, description:{type:"string"},
      memberRunIds:{type:"array",items:{type:"string"}},
      exemplarCritiques:{type:"array",items:{type:"string"}} },
    required:["name","description","memberRunIds","exemplarCritiques"] } } }, required:["clusters"] } } as const;

export async function clusterLabels(labels: Label[]): Promise<ClusterProposal[]> {
  const fails = labels.filter((l) => l.verdict === "fail");
  const res = await getClient().messages.create({
    model: OPUS, max_tokens: 4096,
    thinking: { type: "adaptive" }, output_config: { effort: "high" } as any,
    system: SYSTEM, tools: [TOOL as any], tool_choice: { type:"tool", name:"emit_clusters" },
    messages: [{ role:"user", content: JSON.stringify(fails) }],
  } as any);
  const block = (res.content as any[]).find((b) => b.type === "tool_use");
  return z.array(ClusterProposalSchema).parse(block.input.clusters);
}
```
Install: `npm i @anthropic-ai/sdk`.

- [ ] **Step 4:** Run test → PASS.
- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add Anthropic client and clustering agent"
```

> **Now close the Phase 2 loop:** finish `scripts/critique-harness.ts`, run `npm run critique:harness` against real Opus, and confirm Modes 1 & 2 lump into one ambiguous cluster while the other four separate. Revise `seed-labels.json` until they do. Commit any critique changes.

### Task 5.2: Synthesis agent (LLM/DSL judge builder)

**Files:**
- Create: `src/agents/synthesis.ts`
- Test: `tests/agents/synthesis.test.ts`

**Interfaces:**
- Consumes: a ratified mode (`name`, `description`, member run-ids) + those runs' traces + critiques (build-set only).
- Produces: `synthesizeJudge(mode, buildContext): Promise<{ type:"llm"|"dsl"; spec }>`. The agent **chooses** llm vs dsl; when dsl, its emitted AST is `NodeSchema.parse`-validated before return (retry once on validation failure).

- [ ] **Step 1: Write the failing test** — mock the SDK to return (a) a `dsl` judge whose AST passes `NodeSchema`, assert it's returned typed; (b) an invalid AST first then a valid one, assert the retry path yields the valid judge; (c) an `llm` judge with a `{prompt}` spec, assert passthrough.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3: Write minimal implementation** — system prompt explains both judge types, gives the DSL node vocabulary and the **"root truthy ⇒ mode present ⇒ fail"** convention, and instructs: choose DSL when the mode is deterministically checkable from trace fields (arithmetic, tool-error), else LLM. Two tools: `emit_llm_judge({prompt})` and `emit_dsl_judge({ast})`; `tool_choice:"auto"` so the model picks. Validate `dsl` via `NodeSchema.safeParse`; on failure re-prompt once with the zod error. **Do not hardcode the mode→type mapping.** Build-set restriction enforced by the caller passing only build-set context.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add synthesis agent choosing LLM or DSL judges"
```

### Task 5.3: Thin vertical slice — one mode end-to-end (integration test)

**Files:**
- Create: `tests/integration/vertical-slice.test.ts`

**Interfaces:**
- Consumes: everything above.
- Produces: an integration test (mocked SDK) proving the pipeline for **Mode 3 (arithmetic)**: seed labels → `clusterLabels` → pick the arithmetic cluster → `synthesizeJudge` returns a DSL judge → `runJudgesOnTrace` over the 14 holdout traces → `score` yields an agreement/κ pair. This is the spec's mandated de-risking slice; build it before any remaining screen.

- [ ] **Step 1: Write the failing test** — drive the full chain with a fixture that plants a known arithmetic-mismatch cluster; assert the synthesized DSL judge fires exactly on the mismatch traces and that `score` returns `agreement === 1` against the matching human labels.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Wire a `runSlice(mode, judges)` helper in the test (or `src/eval/pipeline.ts` if reused by screens) that composes the pieces. Fix any interface seams the test exposes.
- [ ] **Step 4:** Run → PASS. **Gate: do not proceed to Phase 7 screens until this passes.**
- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add end-to-end vertical slice for the arithmetic mode"
```

### Task 5.4: Misalignment agent (typed proposals)

**Files:**
- Create: `src/agents/misalignment.ts`
- Test: `tests/agents/misalignment.test.ts`

**Interfaces:**
- Consumes: per-holdout-disagreement context — trace, human verdict+critique, judge verdict+evidence, and for DSL judges the full binding trace.
- Produces: `proposeEdits(disagreements): Promise<Proposal[]>` where `Proposal.type ∈ {narrow, broaden, adjust, split, merge, label_inconsistency}`, each carrying `motivatingRunIds`, a human-readable `rationale`, and a typed `patch` (LLM prompt delta, DSL AST edit, taxonomy split/merge, or the contradicting label pair).

- [ ] **Step 1: Write the failing test** — mock SDK to emit one `adjust` proposal (DSL accessor step change) citing binding-trace evidence, and one `label_inconsistency` proposal referencing a contradicting label pair; assert both validate against `ProposalSchema` and carry `motivatingRunIds`.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement with a zod `ProposalSchema` (discriminated on `type`) and a single `emit_proposals` tool. System prompt: feed the binding trace so the agent diagnoses ("read `days_remaining` from step 3, but balance updated at step 5") rather than guesses; `split`/`merge` amend the taxonomy (Gate 1), the rest edit judges; `label_inconsistency` surfaces contradicting human labels as evidence, not ground truth.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add misalignment agent emitting typed proposals"
```

### Task 5.5: LLM judge caller

**Files:**
- Create: `src/eval/llm-judge.ts`
- Test: `tests/eval/llm-judge.test.ts`

**Interfaces:**
- Consumes: an LLM judge spec `{prompt}` + a `Trace`.
- Produces: `callLlmJudge(spec, trace): Promise<{ fired, evidence:{span,confidence} }>`. `claude-haiku-4-5`, no thinking, one call, structured via a `verdict` tool.

- [ ] **Step 1: Write the failing test** (mock SDK) — assert it returns `{fired:true, evidence:{span,confidence}}` from the tool output and maps a `pass` verdict to `fired:false`.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement: render the trace to text, system = judge prompt + "return verdict via the tool; fired=true means the failure mode IS present", `tool_choice` forces the `verdict` tool with `{verdict:"fail"|"pass", span, confidence}`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add Haiku LLM judge caller"
```

---

## Phase 6 — Session model and state

### Task 6.1: Cookie-keyed session with rate limit + showcase seed

**Files:**
- Create: `src/session/cookie.ts`, `src/session/session.ts`, `src/session/state.ts`
- Test: `tests/session/session.test.ts`

**Interfaces:**
- Produces: `getOrCreateSession()` (reads/sets `hde_session`, creates a `sessions` row, **copies the 26 Priya labels into `labels`**, enforces per-IP creation rate limit); `getSessionState()`/`advanceStage()`; `createShowcaseSession(stage)` frozen at a chosen lifecycle beat.

- [ ] **Step 1: Write the failing test** — with a mocked `db` and `cookies()`, assert a fresh call inserts a session + 26 priya labels and sets the cookie; a second call with the same cookie returns the existing session and does **not** duplicate labels; assert the rate limiter rejects an 11th creation from one IP in the window.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement with `next/headers` cookies; rate-limit via an in-memory/Neon counter keyed by IP+window; showcase seeding inserts a session with `isShowcase:true` prefilled to the requested stage from cached fixtures.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add cookie-keyed session model with seeding and rate limit"
```

### Task 6.2: Server actions for each gate

**Files:**
- Create: `src/app/actions/labels.ts`, `taxonomy.ts`, `synthesis.ts`, `alignment.ts`, `improve.ts`
- Test: `tests/actions/*.test.ts` (one per action, mocked db)

**Interfaces:**
- Produces: `submitLabel`, `ratifyTaxonomy` (approve/rename/split/merge → writes `taxonomyModes` with `ratified:true`), `approveJudge` (edit/flip type/approve → `judges.approved`), `applyProposals` (writes judge/taxonomy edits, bumps `iterations.n`), `requestFreshLabels` (the 3-iteration guard). Each is a `"use server"` action reading the current session.

- [ ] **Step 1–4 (per action):** TDD each: write a test asserting the DB mutation and the returned next-stage; verify fail; implement; verify pass. The 3-iteration guard: `applyProposals` throws/returns a "label fresh runs" state when `iterationCount >= 3`.
- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "Add server actions for label, ratify, synthesize, align, improve"
```

---

## Phase 7 — Screens (build 2 and 5 to depth; others to function)

> Each screen task: write a lightweight component/render test (Vitest + happy-dom for pure components, or a Playwright assertion for the two flagship screens), verify fail, implement, verify pass, commit. UI-heavy steps still follow test-first for the logic (state reducers, keyboard handlers, verdict math); pixel layout is verified by the smoke test in Task 7.8.

### Task 7.1: Screen 1 — Runs (overview + entry)

**Files:** Create `src/app/page.tsx`, `src/components/RunsTable.tsx`. Test `tests/app/runs.test.ts`.
- [ ] Render the 40 runs with per-run label status (labelled/unlabelled, verdict), a labelling-progress meter (X/34), and links into `label/[runId]`. Test the progress computation as a pure function first. Commit: `"Add Runs overview screen"`.

### Task 7.2: Screen 2 — Label (flagship; keyboard-driven)

**Files:** Create `src/app/label/[runId]/page.tsx`, `src/components/TracePane.tsx`, `src/components/LabelForm.tsx`, `src/components/SourceRecordPeek.tsx`. Test `tests/components/label-form.test.ts`.

**Interfaces:** Consumes `getTrace`, `getEmployee`, `submitLabel`. Produces the labelling UX: trace left (tool calls, tool results, **and a peek at the underlying employee/policy source record so fabrications and wrong-record errors are catchable**), verdict + freeform critique right, keyboard-driven (`f`/`p` verdict, `Enter` submit-and-next, `j`/`k` navigate).
- [ ] **Step 1:** Test the keyboard reducer (`keyToAction`) and the "next unlabelled run" selector as pure functions → fail.
- [ ] **Step 2–3:** Implement reducer + selector; build `TracePane` rendering each `Step` by kind with the source-record peek (looks up the employee/policy the step referenced and shows it beside the tool result); build `LabelForm` wired to `submitLabel`; bind keys.
- [ ] **Step 4:** Tests PASS.
- [ ] **Step 5: Commit** `"Add keyboard-driven Label screen with source-record peek"`. **Concentrate effort here — this screen carries the argument.**

### Task 7.3: Screen 3 — Taxonomy ratification (Gate 1)

**Files:** Create `src/app/taxonomy/page.tsx`, `src/components/ClusterCard.tsx`. Test `tests/components/cluster-card.test.ts`.
- [ ] Trigger `clusterLabels` (streaming its reasoning — Task 7.7), render each proposed cluster with member critiques, and offer **approve / rename / split / merge** wired to `ratifyTaxonomy`. Test the split/merge state transforms as pure functions first. Commit: `"Add taxonomy ratification screen (Gate 1)"`.

### Task 7.4: Screen 4 — Evaluator review (Gate 2)

**Files:** Create `src/app/evaluators/page.tsx`, `src/components/JudgeCard.tsx`. Test `tests/components/judge-card.test.ts`.
- [ ] One card per ratified mode: proposed judge **type + agent rationale**, the LLM prompt or the **rendered DSL assertion** (`renderAssertion`), with approve / edit / **flip type** wired to `approveJudge`. Test that a DSL judge renders its assertion and a type-flip re-invokes synthesis. Commit: `"Add evaluator review screen (Gate 2)"`.

### Task 7.5: Screen 5 — Alignment + live tuning (flagship)

**Files:** Create `src/app/alignment/page.tsx`, `src/components/AlignmentHeadline.tsx`, `src/components/DisagreementList.tsx`, `src/components/DslTuner.tsx`. Test `tests/components/dsl-tuner.test.ts`.

**Interfaces:** Consumes `runJudgesOnTrace` over the 14 holdout, `score`, `perJudge`. Produces: agreement + Cohen's κ headline, per-judge FP/FN, disagreement list, and **live tuning for DSL judges** — editing a threshold or flipping a comparison recomputes `score` across all 14 holdout runs **synchronously in the browser** (DSL eval is microseconds), with runs that flip verdict animating in the list.
- [ ] **Step 1:** Test that `DslTuner`'s change handler, given an edited AST, recomputes the holdout verdict vector and the new `{agreement,kappa}` **without any network call** (all 14 traces + judges in client memory) → fail.
- [ ] **Step 2–3:** Precompute LLM-judge verdicts server-side (they can't recompute live); ship DSL judge ASTs + the 14 traces to the client; on edit, re-run `evaluate` for the edited DSL judge, recombine with cached LLM verdicts into composite, recompute `score`, diff the verdict vector to drive flip animations.
- [ ] **Step 4:** Tests PASS.
- [ ] **Step 5: Commit** `"Add Alignment screen with live DSL tuning"`. **Concentrate effort here — most persuasive interaction in the demo.**

### Task 7.6: Screen 6 — Improvement loop (Gate 3)

**Files:** Create `src/app/improve/page.tsx`, `src/components/ProposalCard.tsx`, `src/components/FreeformRecs.tsx`. Test `tests/components/proposal-card.test.ts`.
- [ ] Trigger `proposeEdits` over holdout disagreements (streaming), render typed proposals each with **their motivating disagreements**, a **freeform recommendation box**, and apply → `applyProposals` → re-synthesize → re-score → show alignment delta. `split`/`merge` proposals route back to Gate 1 (taxonomy), not just the judges. Handle `label_inconsistency` by surfacing the contradicting pair and asking which the user stands by (updates the label + re-scores). After the 3rd iteration render the **"tuned against this holdout three times — label fresh runs"** banner (one conditional on `iterationCount`). Commit: `"Add improvement loop screen (Gate 3)"`.

### Task 7.7: Streaming agent reasoning endpoints

**Files:** Create `src/app/api/agents/[agent]/route.ts`, `src/components/ReasoningStream.tsx`. Test `tests/api/stream.test.ts`.
- [ ] SSE route that invokes the requested Opus agent with `stream:true` and forwards `thinking`/text deltas; `ReasoningStream` renders the live reasoning in place of a spinner on screens 3, 4, and 6. Test the SSE frame parser as a pure function. Commit: `"Stream agent reasoning to the UI"`.

### Task 7.8: Screen 7 — Payoff + Playwright smoke test

**Files:** Create `src/app/payoff/page.tsx`; `tests/e2e/smoke.spec.ts` (Playwright, `executablePath:'/opt/pw-browsers/chromium'`).
- [ ] Payoff runs the approved evaluator over the **6 unlabelled runs** and shows each verdict with judge evidence — the "now it works on unseen runs" beat. Playwright smoke test: create session → label a run → land on alignment → assert the κ headline renders. Commit: `"Add payoff screen and Playwright smoke test"`.

---

## Phase 8 — Deploy and cost guardrails

### Task 8.1: Vercel deploy config + env

**Files:** Create/verify `next.config.ts`, add `README` deploy notes; set `DATABASE_URL`, `ANTHROPIC_API_KEY` in Vercel.
- [ ] Confirm build (`npm run build`) passes; document Neon + Anthropic env setup. Commit: `"Add deploy configuration and env documentation"`.

### Task 8.2: Rate-limit + iteration cap + cached showcase (verification)

**Files:** Test `tests/session/guards.test.ts`.
- [ ] Assert (1) per-IP session-creation limit rejects over the cap, (2) `applyProposals` refuses a 4th iteration, (3) the showcase session serves from cached results without invoking any agent. Commit: `"Verify cost guardrails"`.

---

## Out of scope (do not build)

- Live agent execution — traces are pre-baked fixtures.
- Authentication / user accounts.
- Shared or cross-visitor label corpora.
- Persisting evaluators beyond the session.
- Generated-code judges — the DSL covers the deterministic modes with **no execution surface**.

---

## Self-review checklist (run before handing off)

1. **Spec coverage:** every numbered spec section maps to tasks — lifecycle (Phases 5–7), domain/data (Phase 1), corpus/split (1.2, global constraints), seeded critiques (Phase 2), 7 screens (Phase 7), judge execution LLM+DSL (Phases 3, 5.5), alignment + κ (Phase 4), improvement loop with all 5 proposal types + holdout honesty (5.4, 7.6), session + showcase (Phase 6), stack + models (Phases 0, 5), cost guardrails (Phase 8). ✔
2. **Placeholder scan:** deterministic core (DSL, scoring, schema, agents) carries real code; screen tasks carry concrete file lists, interfaces, and test targets rather than TBDs.
3. **Type consistency:** `Verdict`/`V` = `pass|fail`; judge "fired=true ⇒ failure present"; DSL "root truthy ⇒ mode present ⇒ fail"; composite "fail if any judge fires" — held consistent across interpret, run-judges, scoring, and the LLM caller.

## Execution handoff

Save location: `docs/superpowers/plans/2026-07-24-human-driven-evals.md` (this file). Then choose:

- **Subagent-Driven (recommended):** fresh subagent per task via `superpowers:subagent-driven-development` — natural fit given the clean task boundaries here.
- **Inline execution:** batch tasks in-session via `superpowers:executing-plans` with a review checkpoint after each phase.

**Critical path reminder:** Phases 0→1→2→3→4→**5.3 vertical-slice gate**→7. Do not start Phase 7 screens until Task 5.3 passes. Build the seeded critiques (Phase 2) and iterate them against the real clustering agent (after Task 5.1) before depending on them in screens 3–6.
