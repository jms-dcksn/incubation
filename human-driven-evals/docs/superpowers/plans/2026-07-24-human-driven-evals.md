# Human-Driven Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a publicly-deployed demo where a human labels real agent runs, an analysis agent derives a failure taxonomy, the human ratifies it, evaluators are synthesized per mode, and alignment against held-out human labels drives an improvement loop.

**Architecture:** Next.js App Router app on Vercel. Pre-baked agent traces are committed as JSON fixtures; a cookie-keyed ephemeral Postgres session holds labels, taxonomy, judges, and proposals. A deterministic DSL (AST-as-JSON, zod-validated, interpreted — no code execution) implements code judges; Haiku implements LLM judges; three Opus agents (clustering, synthesis, misalignment) provide the automated-assist steps, each followed by a human gate. Alignment is scored on a 14-run holdout with agreement % and Cohen's κ.

**Tech Stack:** Next.js 15 (App Router), TypeScript, Tailwind CSS, Drizzle ORM + Neon Postgres, `@anthropic-ai/sdk`, Vitest for unit tests, zod for validation.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec.

- **Runtime/host:** Next.js App Router on Vercel. Postgres (Neon) accessed via Drizzle. No authentication — cookie-keyed server-side session rows only.
- **LLM judge model:** `claude-haiku-4-5`. One call per (judge × run). Runs **without** thinking.
- **Agent model (clustering, synthesis, misalignment):** `claude-opus-4-8`, called with `thinking: {type: "adaptive"}` and `output_config: {effort: "high"}`.
- **DSL judges are AST-as-JSON validated by zod** — never code as a string. No parsing step, no code execution surface at all. Interpreter target ~200 lines.
- **Composite run verdict:** fail if any judge fires. Alignment computed per-judge and overall.
- **Corpus split (fixed):** 40 total traces. 34 labelled (26 seeded "Priya" + ~8 visitor) + 6 unlabelled payoff. Of the 34 labelled: **20 build set** (judge synthesis reads only these) + **14 holdout** (alignment scored only on these). Taxonomy clustering reads all 34 labels.
- **Planted failure modes (5):** (1) Fabricated policy clause — LLM. (2) Right policy, wrong employee record — LLM. (3) Arithmetic error on balance — DSL/deterministic. (4) Swallowed tool error — DSL/deterministic. (5) Premature closure — LLM. The synthesis agent must *arrive* at the LLM/DSL split itself; the mapping is never hardcoded into synthesis.
- **Label schema:** `{ run_id, verdict: 'pass'|'fail', critique: string, author: 'priya'|'visitor' }`. No tags/categories/checklist at label time.
- **Improvement loop capped at 3 iterations** against the same holdout; after the third, prompt for fresh labels. `label_inconsistency` proposals treat human labels as evidence, not infallible truth.
- **Streaming:** long-running Opus agent calls stream reasoning to the UI, not a spinner.
- **Abuse limits:** rate-limit session creation per IP; serve the showcase (deep-linked frozen) session from cached results rather than re-running.
- **Do not commit secrets.** `ANTHROPIC_API_KEY` and `DATABASE_URL` come from env only.

---

## File Structure

```
human-driven-evals/
  package.json, tsconfig.json, next.config.ts, postcss.config.mjs, tailwind.config.ts
  vitest.config.ts, drizzle.config.ts, .env.example
  src/
    lib/
      trace/types.ts            — Trace / Step / final-answer structured fields
      dsl/ast.ts                — AST node discriminated union + zod schema
      dsl/interpreter.ts        — evaluate(ast, trace) -> { fired, bindings, comparisons }
      judges/types.ts           — Judge, JudgeResult, JudgeVerdict
      judges/llm.ts             — runLlmJudge(judge, trace) on Haiku
      judges/composite.ts       — compositeVerdict(judgeResults)
      alignment/score.ts        — agreement, cohensKappa, perJudgeCounts
      agents/client.ts          — Anthropic client + Opus/Haiku call helpers, streaming
      agents/clustering.ts      — taxonomy from labels
      agents/synthesis.ts       — one judge per ratified mode (chooses LLM|DSL)
      agents/misalignment.ts    — typed improvement proposals
      db/schema.ts              — Drizzle tables
      db/index.ts               — db client
      session/index.ts          — cookie-keyed session bootstrap + Priya seed
      split.ts                  — build/holdout/unlabelled slice membership
    fixtures/
      employees.ts              — ~30 employee records
      policy.ts                 — ~15-clause handbook
      traces/index.ts           — loads + validates the 40 trace JSON files
      traces/*.json             — 40 pre-baked traces
      critiques.ts              — 26 seeded Priya critiques
    app/
      layout.tsx, page.tsx                    — Screen 1: Runs
      label/[runId]/page.tsx                  — Screen 2: Label
      taxonomy/page.tsx                        — Screen 3: Taxonomy ratification
      evaluators/page.tsx                      — Screen 4: Evaluator review
      alignment/page.tsx                       — Screen 5: Alignment + live tuning
      improvement/page.tsx                     — Screen 6: Improvement loop
      payoff/page.tsx                          — Screen 7: Payoff
      api/session/route.ts
      api/labels/route.ts
      api/taxonomy/route.ts, api/taxonomy/ratify/route.ts
      api/synthesis/route.ts, api/judges/route.ts
      api/alignment/route.ts, api/alignment/preview/route.ts
      api/improvement/route.ts, api/improvement/apply/route.ts
      api/payoff/route.ts
    components/
      TracePane.tsx             — renders a trace: tool calls, results, source peek
      CritiqueForm.tsx          — verdict + critique, keyboard-driven
      TaxonomyCard.tsx          — cluster with member critiques, split/merge controls
      EvaluatorCard.tsx         — judge type + rationale + prompt/assertion, edit
      AssertionView.tsx         — binding-trace render for DSL judges (clickable leaves)
      AlignmentPanel.tsx        — agreement/κ, per-judge FP/FN, disagreement list
      LiveTuner.tsx             — DSL edit form recomputing alignment client-side
      ProposalCard.tsx          — typed proposal + motivating disagreements
      ReasoningStream.tsx       — streams Opus reasoning tokens
  tests/
    dsl/interpreter.test.ts, dsl/ast.test.ts
    alignment/score.test.ts
    judges/composite.test.ts
    fixtures/traces.test.ts, fixtures/critiques.test.ts
    split.test.ts
    session/session.test.ts
```

---

# PHASE 0 — Scaffolding

### Task 1: Project scaffold, tooling, and test harness

**Files:**
- Create: `package.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `tailwind.config.ts`, `vitest.config.ts`, `.env.example`, `src/app/layout.tsx`, `src/app/page.tsx`, `tests/smoke.test.ts`

**Interfaces:**
- Produces: a runnable Next.js app and a working `npm test` (Vitest) command that all later tasks build on.

- [ ] **Step 1: Write the failing smoke test**

`tests/smoke.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';

describe('toolchain', () => {
  it('runs vitest', () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 2: Run it to verify the harness is missing**

Run: `npm test`
Expected: FAIL — `vitest` not found / no package.json.

- [ ] **Step 3: Scaffold the project**

Create `package.json`:
```json
{
  "name": "human-driven-evals",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run",
    "test:watch": "vitest",
    "db:generate": "drizzle-kit generate",
    "db:migrate": "drizzle-kit migrate"
  },
  "dependencies": {
    "@anthropic-ai/sdk": "^0.65.0",
    "drizzle-orm": "^0.44.0",
    "next": "^15.5.0",
    "postgres": "^3.4.5",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "zod": "^4.1.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "@types/react": "^19.1.0",
    "@types/react-dom": "^19.1.0",
    "drizzle-kit": "^0.31.0",
    "tailwindcss": "^4.1.0",
    "@tailwindcss/postcss": "^4.1.0",
    "typescript": "^5.6.0",
    "vitest": "^3.0.0"
  }
}
```

Create `tsconfig.json` with `"paths": { "@/*": ["./src/*"] }`, `"strict": true`, `"jsx": "preserve"`, `moduleResolution` `"bundler"`, and the Next.js plugin. Create `vitest.config.ts`:
```typescript
import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: { environment: 'node', include: ['tests/**/*.test.ts'] },
});
```

Create `next.config.ts`, `postcss.config.mjs` (`{ plugins: { '@tailwindcss/postcss': {} } }`), `tailwind.config.ts`, minimal `src/app/layout.tsx` (html/body + Tailwind import) and `src/app/page.tsx` (placeholder `<main>Runs</main>`). Create `.env.example`:
```
ANTHROPIC_API_KEY=
DATABASE_URL=
```

- [ ] **Step 4: Install and run the test**

Run: `npm install && npm test`
Expected: PASS (smoke test green).

- [ ] **Step 5: Verify the app builds**

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold Next.js + Vitest + Drizzle toolchain"
```

---

# PHASE 1 — Data model, fixtures, and session

### Task 2: Trace types and trace loader

**Files:**
- Create: `src/lib/trace/types.ts`, `src/fixtures/traces/index.ts`, `src/fixtures/traces/run-001.json`, `tests/fixtures/traces.test.ts`

**Interfaces:**
- Produces:
  - `type Trace = { run_id: string; user_message: string; steps: Step[]; final_answer: FinalAnswer }`
  - `type Step` (discriminated on `kind`): `ToolCallStep | ToolResultStep | AssistantStep`
  - `ToolResultStep = { kind: 'tool_result'; index: number; tool: string; data: Record<string, unknown>; error: string | null }`
  - `FinalAnswer = { text: string; fields: Record<string, unknown> }`
  - `loadTraces(): Trace[]` and `traceZodSchema` (zod) used to validate every JSON fixture at load.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/traces.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { loadTraces } from '@/fixtures/traces';
import { traceZodSchema } from '@/lib/trace/types';

describe('trace loader', () => {
  it('loads and validates at least one trace', () => {
    const traces = loadTraces();
    expect(traces.length).toBeGreaterThan(0);
    for (const t of traces) expect(() => traceZodSchema.parse(t)).not.toThrow();
  });
  it('assigns monotonically increasing step indices', () => {
    const t = loadTraces()[0];
    t.steps.forEach((s, i) => expect(s.index).toBe(i));
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- traces`
Expected: FAIL — module not found.

- [ ] **Step 3: Define the types and zod schema**

`src/lib/trace/types.ts`:
```typescript
import { z } from 'zod';

export const toolCallStep = z.object({
  kind: z.literal('tool_call'), index: z.number().int(),
  tool: z.string(), args: z.record(z.string(), z.unknown()),
});
export const toolResultStep = z.object({
  kind: z.literal('tool_result'), index: z.number().int(),
  tool: z.string(), data: z.record(z.string(), z.unknown()),
  error: z.string().nullable(),
});
export const assistantStep = z.object({
  kind: z.literal('assistant'), index: z.number().int(), text: z.string(),
});
export const stepSchema = z.discriminatedUnion('kind', [toolCallStep, toolResultStep, assistantStep]);

export const finalAnswerSchema = z.object({
  text: z.string(), fields: z.record(z.string(), z.unknown()),
});
export const traceZodSchema = z.object({
  run_id: z.string(), user_message: z.string(),
  steps: z.array(stepSchema), final_answer: finalAnswerSchema,
});

export type Step = z.infer<typeof stepSchema>;
export type ToolResultStep = z.infer<typeof toolResultStep>;
export type FinalAnswer = z.infer<typeof finalAnswerSchema>;
export type Trace = z.infer<typeof traceZodSchema>;
```

- [ ] **Step 4: Write the loader and one real trace**

`src/fixtures/traces/run-001.json` — a clean PASS trace (Priya asks a parental-leave question, agent looks up employee, searches policy, answers correctly), with `final_answer.fields` carrying the structured claims (e.g. `{ "stated_days": 12 }`) and each `tool_result` carrying `data` + `error: null`.

`src/fixtures/traces/index.ts`:
```typescript
import { traceZodSchema, type Trace } from '@/lib/trace/types';
import run001 from './run-001.json';

const RAW: unknown[] = [run001];

export function loadTraces(): Trace[] {
  return RAW.map((r) => traceZodSchema.parse(r));
}
```
Enable `resolveJsonModule` in `tsconfig.json` if not already on.

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm test -- traces`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: trace types, zod schema, and loader with one fixture"
```

---

### Task 3: Domain fixtures — employees and policy handbook

**Files:**
- Create: `src/fixtures/employees.ts`, `src/fixtures/policy.ts`, `tests/fixtures/domain.test.ts`

**Interfaces:**
- Produces:
  - `type Employee = { id: string; name: string; tenure_months: number; location: string; employment_type: 'full_time'|'part_time'|'contractor'; accrued_leave: number; remaining_balance: number }`
  - `EMPLOYEES: Employee[]` (~30), `getEmployee(name: string): Employee | undefined`
  - `type PolicyClause = { id: string; title: string; text: string; jurisdiction: string | null }`
  - `POLICY: PolicyClause[]` (~15), `searchPolicy(query: string): PolicyClause[]`
- These back the `lookup_employee` / `search_policy` tools and the Label screen's "source record peek" so fabrications are catchable.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/domain.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { EMPLOYEES, getEmployee } from '@/fixtures/employees';
import { POLICY, searchPolicy } from '@/fixtures/policy';

describe('domain fixtures', () => {
  it('has ~30 employees with unique names', () => {
    expect(EMPLOYEES.length).toBeGreaterThanOrEqual(28);
    expect(new Set(EMPLOYEES.map(e => e.name)).size).toBe(EMPLOYEES.length);
  });
  it('has ~15 policy clauses with unique ids', () => {
    expect(POLICY.length).toBeGreaterThanOrEqual(14);
    expect(new Set(POLICY.map(c => c.id)).size).toBe(POLICY.length);
  });
  it('lookup is case-insensitive', () => {
    const name = EMPLOYEES[0].name;
    expect(getEmployee(name.toLowerCase())?.id).toBe(EMPLOYEES[0].id);
  });
  it('policy search matches on title and text tokens', () => {
    expect(searchPolicy('parental leave').length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- domain`
Expected: FAIL — modules not found.

- [ ] **Step 3: Author the fixtures**

`src/fixtures/employees.ts`: define the `Employee` type and a hand-authored `EMPLOYEES` array of ~30 records varying tenure, location (mix of jurisdictions — e.g. `CA-US`, `NY-US`, `UK`, `DE`), employment type, and balances. Add:
```typescript
export function getEmployee(name: string): Employee | undefined {
  const n = name.trim().toLowerCase();
  return EMPLOYEES.find(e => e.name.toLowerCase() === n);
}
```

`src/fixtures/policy.ts`: define `PolicyClause` and a ~15-clause `POLICY` array covering parental leave, carry-over caps, jurisdiction-specific entitlements, and notice periods. Add a simple token-overlap `searchPolicy`:
```typescript
export function searchPolicy(query: string): PolicyClause[] {
  const q = query.toLowerCase().split(/\s+/).filter(Boolean);
  return POLICY
    .map(c => ({ c, score: q.filter(t => (c.title + ' ' + c.text).toLowerCase().includes(t)).length }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(x => x.c);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- domain`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: employee records and policy handbook fixtures"
```

---

### Task 4: The 40-trace corpus with planted failure modes

> **This task is content-heavy and load-bearing.** The five modes must each recur across multiple runs so clustering has structure to find. Deterministic modes (3, 4) must carry the structured `data`/`fields` the DSL will read. Author traces against the real domain fixtures so the "source peek" reveals fabrications.

**Files:**
- Create: `src/fixtures/traces/run-002.json` … `run-040.json`, `src/fixtures/traces/manifest.ts`
- Modify: `src/fixtures/traces/index.ts` (import all 40)
- Test: `tests/fixtures/corpus.test.ts`

**Interfaces:**
- Produces: `TRACE_MANIFEST: { run_id: string; planted_modes: number[] }[]` — the ground-truth mode map, used **only** in tests and for authoring self-checks, never fed to synthesis.

- [ ] **Step 1: Write the failing corpus test**

`tests/fixtures/corpus.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { loadTraces } from '@/fixtures/traces';
import { TRACE_MANIFEST } from '@/fixtures/traces/manifest';

describe('corpus', () => {
  const traces = loadTraces();
  it('has exactly 40 traces with unique ids', () => {
    expect(traces.length).toBe(40);
    expect(new Set(traces.map(t => t.run_id)).size).toBe(40);
  });
  it('~35% exhibit at least one planted failure', () => {
    const failing = TRACE_MANIFEST.filter(m => m.planted_modes.length > 0).length;
    expect(failing).toBeGreaterThanOrEqual(12);
    expect(failing).toBeLessThanOrEqual(16);
  });
  it('every mode 1..5 appears in multiple runs', () => {
    for (const mode of [1, 2, 3, 4, 5]) {
      const count = TRACE_MANIFEST.filter(m => m.planted_modes.includes(mode)).length;
      expect(count).toBeGreaterThanOrEqual(2);
    }
  });
  it('mode 3 runs expose numeric fields for the DSL', () => {
    for (const m of TRACE_MANIFEST.filter(x => x.planted_modes.includes(3))) {
      const t = traces.find(t => t.run_id === m.run_id)!;
      expect(typeof t.final_answer.fields.stated_days).toBe('number');
      expect(t.steps.some(s => s.kind === 'tool_result' && 'days_remaining' in (s as any).data)).toBe(true);
    }
  });
  it('mode 4 runs contain a tool_result with a non-null error', () => {
    for (const m of TRACE_MANIFEST.filter(x => x.planted_modes.includes(4))) {
      const t = traces.find(t => t.run_id === m.run_id)!;
      expect(t.steps.some(s => s.kind === 'tool_result' && (s as any).error !== null)).toBe(true);
    }
  });
  it('manifest run_ids all resolve to a trace', () => {
    for (const m of TRACE_MANIFEST) expect(traces.some(t => t.run_id === m.run_id)).toBe(true);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- corpus`
Expected: FAIL — only run-001 exists.

- [ ] **Step 3: Author the remaining 39 traces**

Hand-author `run-002.json` … `run-040.json`. Distribution (matches ~35% failing, each mode ≥ 2 runs, some multi-mode):
- ~26 clean PASS runs across varied employee/policy questions.
- Mode 1 (fabricated clause): 3 runs — `final_answer.text` cites a clause id/title absent from `POLICY`; `final_answer.fields.cited_clause_ids` lists the fabricated id.
- Mode 2 (wrong employee): 3 runs — `tool_call lookup_employee` args name ≠ the person in `user_message`; `final_answer.fields.about_employee_id` points at the wrong record.
- Mode 3 (arithmetic error): 3 runs — `tool_result` for the balance tool has `data.days_remaining = X`; `final_answer.fields.stated_days = Y ≠ X`.
- Mode 4 (swallowed tool error): 3 runs — a `tool_result` has `error != null` yet the agent answers confidently; `final_answer.fields.acknowledged_error = false`.
- Mode 5 (premature closure): 2–3 runs — `final_answer.text` says "you're all set" / "hope that helps" without addressing the `user_message`; `final_answer.fields.addressed_question = false`.
- Author 1–2 **multi-mode** runs (e.g. mode 2 + mode 3) so composite verdict is exercised.

Create `manifest.ts` mapping each `run_id → planted_modes`. Update `index.ts` `RAW` to import all 40 JSON files.

- [ ] **Step 4: Run the corpus test to verify it passes**

Run: `npm test -- corpus`
Expected: PASS.

- [ ] **Step 5: Full validation pass**

Run: `npm test -- traces corpus`
Expected: PASS (all 40 still satisfy `traceZodSchema`).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: 40-trace corpus with planted failure modes and ground-truth manifest"
```

---

### Task 5: The 26 seeded critiques (highest-risk asset)

> The spec flags these as **load-bearing**: they must read as genuinely human, vary in phrasing/length, and cluster into four clean groups **plus one deliberately ambiguous cluster** where modes 1 and 2 both read as *"it told me something untrue about my leave."* Write these to be split by a human at Gate 1, not cleanly separable by the clustering agent. They will be iterated against the real clustering agent in Task 12.

**Files:**
- Create: `src/fixtures/critiques.ts`, `tests/fixtures/critiques.test.ts`

**Interfaces:**
- Produces: `SEEDED_CRITIQUES: { run_id: string; verdict: 'pass'|'fail'; critique: string }[]` (author `'priya'` applied at seed time). Every `run_id` references a real trace.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/critiques.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { SEEDED_CRITIQUES } from '@/fixtures/critiques';
import { loadTraces } from '@/fixtures/traces';
import { TRACE_MANIFEST } from '@/fixtures/traces/manifest';

describe('seeded critiques', () => {
  const ids = new Set(loadTraces().map(t => t.run_id));
  it('has 26 critiques over real runs', () => {
    expect(SEEDED_CRITIQUES.length).toBe(26);
    for (const c of SEEDED_CRITIQUES) expect(ids.has(c.run_id)).toBe(true);
  });
  it('fail verdicts align with planted modes (sanity, not leakage)', () => {
    for (const c of SEEDED_CRITIQUES.filter(c => c.verdict === 'fail')) {
      const modes = TRACE_MANIFEST.find(m => m.run_id === c.run_id)!.planted_modes;
      expect(modes.length).toBeGreaterThan(0);
    }
  });
  it('critiques vary in length (not templated)', () => {
    const lens = SEEDED_CRITIQUES.map(c => c.critique.length);
    expect(Math.max(...lens) - Math.min(...lens)).toBeGreaterThan(80);
  });
  it('covers every planted mode at least twice among the 26', () => {
    for (const mode of [1, 2, 3, 4, 5]) {
      const n = SEEDED_CRITIQUES.filter(c =>
        TRACE_MANIFEST.find(m => m.run_id === c.run_id)!.planted_modes.includes(mode)).length;
      expect(n).toBeGreaterThanOrEqual(2);
    }
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- critiques`
Expected: FAIL — module not found.

- [ ] **Step 3: Author the 26 critiques**

Write `SEEDED_CRITIQUES` as first-person, varied critiques. Guidance:
- ~14–16 `pass` critiques ranging from terse ("looks right") to a couple of sentences.
- Mode 3 critiques mention the number being off ("said I had 12 left but the record clearly shows 14").
- Mode 4 critiques mention confident answers over a failure ("the lookup errored but it just plowed ahead").
- Mode 5 critiques mention being brushed off ("wrapped up before actually answering my carry-over question").
- **Modes 1 and 2 critiques are phrased the same way on purpose** — "told me something about my leave that wasn't true," "the info it gave me was just wrong" — so the cluster is genuinely ambiguous.
Assign each critique to a real `run_id` from the manifest so `pass`/`fail` verdicts are internally consistent.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- critiques`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: 26 seeded Priya critiques with designed ambiguous cluster"
```

---

### Task 6: Corpus split (build / holdout / unlabelled)

**Files:**
- Create: `src/lib/split.ts`, `tests/split.test.ts`

**Interfaces:**
- Produces:
  - `SLICE: Record<string, 'build'|'holdout'|'unlabelled'>` keyed by `run_id`
  - `buildRunIds(): string[]` (20), `holdoutRunIds(): string[]` (14), `unlabelledRunIds(): string[]` (6)
  - Invariant enforced: the 34 labelled ids (build ∪ holdout) exactly equal the seeded+visitor-eligible set; unlabelled ids carry no seeded critique.

- [ ] **Step 1: Write the failing test**

`tests/split.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { buildRunIds, holdoutRunIds, unlabelledRunIds } from '@/lib/split';
import { SEEDED_CRITIQUES } from '@/fixtures/critiques';

describe('split', () => {
  it('partitions 40 into 20/14/6 with no overlap', () => {
    const b = buildRunIds(), h = holdoutRunIds(), u = unlabelledRunIds();
    expect([b.length, h.length, u.length]).toEqual([20, 14, 6]);
    expect(new Set([...b, ...h, ...u]).size).toBe(40);
  });
  it('unlabelled runs carry no seeded critique', () => {
    const seeded = new Set(SEEDED_CRITIQUES.map(c => c.run_id));
    for (const id of unlabelledRunIds()) expect(seeded.has(id)).toBe(false);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- split`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the split**

`src/lib/split.ts`: define constant `run_id` arrays for the three slices (chosen so the 26 seeded critiques all fall in build ∪ holdout, failing runs are spread across build and holdout, and the 6 unlabelled include at least a couple of planted failures for the payoff screen). Export the three accessors and a `SLICE` map built from them.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- split`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: fixed build/holdout/unlabelled corpus split"
```

---

### Task 7: Drizzle schema, db client, and migration

**Files:**
- Create: `src/db/schema.ts`, `src/db/index.ts`, `drizzle.config.ts`
- Test: `tests/db/schema.test.ts`

**Interfaces:**
- Produces Drizzle tables (all keyed by `session_id` except `sessions`):
  - `sessions(id uuid pk, cookie_token text unique, created_at, stage text, frozen boolean)`
  - `labels(id, session_id, run_id, verdict text, critique text, author text, created_at)` — unique `(session_id, run_id)`
  - `taxonomies(id, session_id, status text, created_at)` and `taxonomy_modes(id, taxonomy_id, name text, description text, member_run_ids jsonb, ratified boolean)`
  - `judges(id, session_id, mode_id, kind text, spec jsonb, rationale text, approved boolean)` — `spec` holds a prompt string (LLM) or a validated AST (DSL)
  - `proposals(id, session_id, type text, target_judge_id, payload jsonb, motivating_run_ids jsonb, status text)`
  - `iterations(id, session_id, index int, agreement real, kappa real, created_at)`
- `db` exported from `src/db/index.ts`; a `schema` object re-exported for tests.

- [ ] **Step 1: Write the failing test**

`tests/db/schema.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import * as schema from '@/db/schema';

describe('db schema', () => {
  it('exports the required tables', () => {
    for (const t of ['sessions', 'labels', 'taxonomies', 'taxonomyModes',
                     'judges', 'proposals', 'iterations']) {
      expect(schema).toHaveProperty(t);
    }
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- schema`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement schema, client, and drizzle config**

`src/db/schema.ts`: define the tables above using `drizzle-orm/pg-core` (`pgTable`, `uuid`, `text`, `boolean`, `jsonb`, `integer`, `real`, `timestamp`, `uniqueIndex`). `src/db/index.ts`:
```typescript
import { drizzle } from 'drizzle-orm/postgres-js';
import postgres from 'postgres';
import * as schema from './schema';

const client = postgres(process.env.DATABASE_URL!, { prepare: false });
export const db = drizzle(client, { schema });
export { schema };
```
`drizzle.config.ts` points at `src/db/schema.ts`, dialect `postgresql`, `dbCredentials.url` from `DATABASE_URL`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- schema`
Expected: PASS.

- [ ] **Step 5: Generate the migration**

Run: `npm run db:generate`
Expected: a migration file appears under `drizzle/`. (Applying it requires a live `DATABASE_URL`; generation validates the schema compiles.)

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: Drizzle schema, db client, and initial migration"
```

---

### Task 8: Cookie-keyed session bootstrap with Priya seed

**Files:**
- Create: `src/lib/session/index.ts`, `src/app/api/session/route.ts`, `tests/session/session.test.ts`

**Interfaces:**
- Consumes: `db`, `schema`, `SEEDED_CRITIQUES`.
- Produces:
  - `getOrCreateSession(): Promise<{ id: string; stage: string; created: boolean }>` — reads the `hde_session` cookie, creates a row + writes the cookie if absent, and on creation **inserts all 26 seeded labels** (`author: 'priya'`).
  - `seedLabels(sessionId: string): Promise<void>` — pure insert helper, unit-testable against a mocked `db`.

- [ ] **Step 1: Write the failing test**

`tests/session/session.test.ts` — unit-test `seedLabels` with a mocked db, asserting 26 rows are prepared with `author: 'priya'`:
```typescript
import { describe, it, expect, vi } from 'vitest';
import { buildSeedRows } from '@/lib/session';
import { SEEDED_CRITIQUES } from '@/fixtures/critiques';

describe('session seeding', () => {
  it('builds one seed row per seeded critique, all authored by priya', () => {
    const rows = buildSeedRows('sess-1');
    expect(rows.length).toBe(SEEDED_CRITIQUES.length);
    expect(rows.every(r => r.author === 'priya' && r.sessionId === 'sess-1')).toBe(true);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- session`
Expected: FAIL — `buildSeedRows` not exported.

- [ ] **Step 3: Implement session logic**

In `src/lib/session/index.ts` export a pure `buildSeedRows(sessionId)` mapping `SEEDED_CRITIQUES` → label insert rows, and `getOrCreateSession()` using `next/headers` `cookies()` + `db`. Per-IP rate limiting on creation: a small in-memory token bucket keyed by IP (documented as best-effort for the demo). The `POST /api/session` route calls `getOrCreateSession` and returns the session.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- session`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: cookie-keyed session bootstrap with Priya label seed"
```

---

# PHASE 2 — Core engine (deterministic, TDD-heavy)

### Task 9: DSL AST types and zod validation

**Files:**
- Create: `src/lib/dsl/ast.ts`, `tests/dsl/ast.test.ts`

**Interfaces:**
- Produces:
  - `type StepSelector = { kind: 'tool_call'|'tool_result'|'final_answer'|'assistant'; tool?: string; occurrence?: number }`
  - `AstNode` discriminated union on `op`: `accessor | literal | compare | exists | notExists | and | or | not | contains`
  - `astSchema` (zod) that rejects unknown ops, bad comparators, and malformed nodes; `parseAst(json: unknown): AstNode` throwing on invalid input.

- [ ] **Step 1: Write the failing test**

`tests/dsl/ast.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { parseAst } from '@/lib/dsl/ast';

const valid = {
  op: 'compare', cmp: 'neq',
  left:  { op: 'accessor', step: { kind: 'tool_result', tool: 'leave_balance' }, path: 'days_remaining' },
  right: { op: 'accessor', step: { kind: 'final_answer' }, path: 'stated_days' },
};

describe('AST validation', () => {
  it('accepts a well-formed compare node', () => {
    expect(() => parseAst(valid)).not.toThrow();
  });
  it('rejects an unknown op', () => {
    expect(() => parseAst({ op: 'frobnicate' })).toThrow();
  });
  it('rejects an invalid comparator', () => {
    expect(() => parseAst({ ...valid, cmp: 'approx' })).toThrow();
  });
  it('accepts literal with numeric tolerance', () => {
    expect(() => parseAst({ op: 'literal', value: 14, tolerance: 0.5 })).not.toThrow();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- dsl/ast`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the AST schema**

`src/lib/dsl/ast.ts` — build the recursive zod union with `z.lazy`:
```typescript
import { z } from 'zod';

export const stepSelector = z.object({
  kind: z.enum(['tool_call', 'tool_result', 'final_answer', 'assistant']),
  tool: z.string().optional(),
  occurrence: z.number().int().nonnegative().optional(),
});

export const astSchema: z.ZodType<AstNode> = z.lazy(() =>
  z.discriminatedUnion('op', [
    z.object({ op: z.literal('accessor'), step: stepSelector, path: z.string() }),
    z.object({ op: z.literal('literal'), value: z.unknown(), tolerance: z.number().optional() }),
    z.object({ op: z.literal('compare'),
      cmp: z.enum(['eq', 'neq', 'gt', 'lt', 'gte', 'lte']),
      left: astSchema, right: astSchema }),
    z.object({ op: z.literal('exists'), arg: astSchema }),
    z.object({ op: z.literal('notExists'), arg: astSchema }),
    z.object({ op: z.literal('and'), args: z.array(astSchema).min(1) }),
    z.object({ op: z.literal('or'), args: z.array(astSchema).min(1) }),
    z.object({ op: z.literal('not'), arg: astSchema }),
    z.object({ op: z.literal('contains'), haystack: astSchema, needle: astSchema }),
  ])
);

export type StepSelector = z.infer<typeof stepSelector>;
export type AstNode =
  | { op: 'accessor'; step: StepSelector; path: string }
  | { op: 'literal'; value: unknown; tolerance?: number }
  | { op: 'compare'; cmp: 'eq'|'neq'|'gt'|'lt'|'gte'|'lte'; left: AstNode; right: AstNode }
  | { op: 'exists'; arg: AstNode }
  | { op: 'notExists'; arg: AstNode }
  | { op: 'and'; args: AstNode[] }
  | { op: 'or'; args: AstNode[] }
  | { op: 'not'; arg: AstNode }
  | { op: 'contains'; haystack: AstNode; needle: AstNode };

export function parseAst(json: unknown): AstNode {
  return astSchema.parse(json);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- dsl/ast`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: DSL AST discriminated union with zod validation"
```

---

### Task 10: DSL interpreter with binding trace

**Files:**
- Create: `src/lib/dsl/interpreter.ts`, `tests/dsl/interpreter.test.ts`

**Interfaces:**
- Consumes: `AstNode`, `Trace`.
- Produces:
  - `type Binding = { path: string; stepIndex: number | null; value: unknown }`
  - `type ComparisonRecord = { cmp: string; left: unknown; right: unknown; result: boolean }`
  - `type EvalResult = { fired: boolean; bindings: Binding[]; comparisons: ComparisonRecord[] }`
  - `evaluate(ast: AstNode, trace: Trace): EvalResult` — a node evaluating `true` at the root means the judge **fires** (failure detected). Every accessor resolved is recorded in `bindings`; every compare in `comparisons`. This binding trace is later consumed by the misalignment agent and the `AssertionView` UI.

- [ ] **Step 1: Write the failing tests**

`tests/dsl/interpreter.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { evaluate } from '@/lib/dsl/interpreter';
import type { Trace } from '@/lib/trace/types';
import type { AstNode } from '@/lib/dsl/ast';

const trace: Trace = {
  run_id: 'r', user_message: 'how many days do I have left?',
  steps: [
    { kind: 'tool_call', index: 0, tool: 'leave_balance', args: { name: 'A' } },
    { kind: 'tool_result', index: 1, tool: 'leave_balance', data: { days_remaining: 14 }, error: null },
  ],
  final_answer: { text: 'You have 12 days.', fields: { stated_days: 12 } },
};

const arithmetic: AstNode = {
  op: 'compare', cmp: 'neq',
  left:  { op: 'accessor', step: { kind: 'tool_result', tool: 'leave_balance' }, path: 'days_remaining' },
  right: { op: 'accessor', step: { kind: 'final_answer' }, path: 'stated_days' },
};

describe('DSL interpreter', () => {
  it('fires on arithmetic mismatch and records bindings', () => {
    const r = evaluate(arithmetic, trace);
    expect(r.fired).toBe(true);
    expect(r.bindings).toContainEqual({ path: 'days_remaining', stepIndex: 1, value: 14 });
    expect(r.bindings).toContainEqual({ path: 'stated_days', stepIndex: null, value: 12 });
    expect(r.comparisons[0]).toMatchObject({ cmp: 'neq', left: 14, right: 12, result: true });
  });
  it('does not fire when the numbers agree', () => {
    const agree = { ...trace, final_answer: { text: '', fields: { stated_days: 14 } } };
    expect(evaluate(arithmetic, agree).fired).toBe(false);
  });
  it('exists detects a swallowed tool error', () => {
    const errored: Trace = { ...trace, steps: [
      { kind: 'tool_result', index: 0, tool: 'leave_balance', data: {}, error: 'not found' },
    ]};
    const ast: AstNode = { op: 'exists',
      arg: { op: 'accessor', step: { kind: 'tool_result', tool: 'leave_balance' }, path: '$error' } };
    expect(evaluate(ast, errored).fired).toBe(true);
  });
  it('eq respects literal tolerance', () => {
    const ast: AstNode = { op: 'compare', cmp: 'eq',
      left: { op: 'accessor', step: { kind: 'tool_result', tool: 'leave_balance' }, path: 'days_remaining' },
      right: { op: 'literal', value: 14.3, tolerance: 0.5 } };
    expect(evaluate(ast, trace).fired).toBe(true);
  });
  it('occurrence selects the nth matching step', () => {
    const two: Trace = { ...trace, steps: [
      { kind: 'tool_result', index: 0, tool: 'leave_balance', data: { days_remaining: 1 }, error: null },
      { kind: 'tool_result', index: 1, tool: 'leave_balance', data: { days_remaining: 14 }, error: null },
    ]};
    const ast: AstNode = { op: 'accessor',
      step: { kind: 'tool_result', tool: 'leave_balance', occurrence: 1 }, path: 'days_remaining' };
    expect(evaluate({ op: 'compare', cmp: 'eq', left: ast,
      right: { op: 'literal', value: 14 } }, two).fired).toBe(true);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm test -- dsl/interpreter`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the interpreter (~200 lines)**

`src/lib/dsl/interpreter.ts`: implement `evaluate` with a recursive `evalNode(node): unknown` closure that pushes to `bindings`/`comparisons`. Rules:
- **accessor:** resolve the step via the selector (`final_answer` → the trace's `final_answer`, `stepIndex = null`; otherwise the `occurrence`-th step matching `kind` and optional `tool`). Path `$error` reads the step's `error`; path `$text` reads `.text`; any other path reads from `final_answer.fields` or the step's `data`. Record `{ path, stepIndex, value }`. Missing → `undefined`.
- **literal:** returns `{ __value, __tolerance }` internally so `compare` can pick up tolerance; expose `.value` when used as a plain operand.
- **compare:** evaluate both sides to primitives; if either operand carried a tolerance, `eq`/`neq` use `Math.abs(l-r) <= tol`; numeric comparators coerce to `Number`. Push a `ComparisonRecord`.
- **exists/notExists:** truthy check on `value !== undefined && value !== null`.
- **and/or/not:** boolean composition over child results.
- **contains:** `String(haystack).includes(String(needle))` or `Array.isArray(haystack) && haystack.includes(needle)`.
- Root result coerced to boolean = `fired`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- dsl/interpreter`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: DSL interpreter with binding trace"
```

---

### Task 11: LLM judge runner and composite verdict

**Files:**
- Create: `src/lib/agents/client.ts`, `src/lib/judges/types.ts`, `src/lib/judges/llm.ts`, `src/lib/judges/composite.ts`, `tests/judges/composite.test.ts`

**Interfaces:**
- Produces:
  - `src/lib/agents/client.ts`: `anthropic` (SDK client), `callHaiku({ system, user }): Promise<string>`, and `streamOpus({ system, user, onText }): Promise<string>` (used by Phase 3 agents; `thinking:{type:'adaptive'}`, `output_config:{effort:'high'}`).
  - `src/lib/judges/types.ts`: `type JudgeKind = 'llm'|'dsl'`; `type Judge = { id: string; modeId: string; kind: JudgeKind; spec: string | AstNode; rationale: string }`; `type JudgeResult = { judgeId: string; runId: string; fired: boolean; evidence: string | null; confidence: number | null; binding?: EvalResult }`.
  - `src/lib/judges/llm.ts`: `runLlmJudge(judge, trace): Promise<JudgeResult>` — one Haiku call, prompt embeds the mode description + serialized trace, model returns strict JSON `{ verdict: 'pass'|'fail', evidence: string, confidence: number }`.
  - `src/lib/judges/composite.ts`: `compositeVerdict(results: JudgeResult[]): 'pass'|'fail'` — **fail iff any judge fired.**

- [ ] **Step 1: Write the failing test (composite is pure — TDD it)**

`tests/judges/composite.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { compositeVerdict } from '@/lib/judges/composite';

const r = (fired: boolean) => ({ judgeId: 'j', runId: 'r', fired, evidence: null, confidence: null });

describe('composite verdict', () => {
  it('fails if any judge fired', () => {
    expect(compositeVerdict([r(false), r(true), r(false)])).toBe('fail');
  });
  it('passes only when all judges pass', () => {
    expect(compositeVerdict([r(false), r(false)])).toBe('pass');
  });
  it('passes on an empty judge set', () => {
    expect(compositeVerdict([])).toBe('pass');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- composite`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement client, types, llm runner, and composite**

`client.ts`: instantiate `new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY })`. `callHaiku` uses `model: 'claude-haiku-4-5'`, no thinking, returns the concatenated text. `streamOpus` uses `model: 'claude-opus-4-8'`, `thinking: { type: 'adaptive' }`, `output_config: { effort: 'high' }`, streams text via `onText`. `llm.ts` builds the judge prompt (mode name + description + `JSON.stringify(trace)`), calls `callHaiku`, and parses the JSON verdict into a `JudgeResult` (`fired = verdict === 'fail'`). `composite.ts` implements `compositeVerdict` as `results.some(r => r.fired) ? 'fail' : 'pass'`.

- [ ] **Step 4: Run the composite test to verify it passes**

Run: `npm test -- composite`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Anthropic client, Haiku LLM judge runner, composite verdict"
```

---

### Task 12: Alignment scoring — agreement, Cohen's κ, per-judge FP/FN

**Files:**
- Create: `src/lib/alignment/score.ts`, `tests/alignment/score.test.ts`

**Interfaces:**
- Consumes: composite results and human labels for the holdout runs.
- Produces:
  - `type RunOutcome = { runId: string; human: 'pass'|'fail'; machine: 'pass'|'fail' }`
  - `agreement(outcomes: RunOutcome[]): number` (0..1)
  - `cohensKappa(outcomes: RunOutcome[]): number`
  - `perJudgeCounts(results: JudgeResult[], humanByRun: Record<string,'pass'|'fail'>): Record<string, { fp: number; fn: number }>` — FP = judge fired but human passed; FN = judge silent but human failed.
  - `type AlignmentReport = { agreement: number; kappa: number; disagreements: RunOutcome[]; perJudge: Record<string, {fp:number;fn:number}> }` and `scoreAlignment(...)` assembling it.

- [ ] **Step 1: Write the failing tests**

`tests/alignment/score.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { agreement, cohensKappa, perJudgeCounts } from '@/lib/alignment/score';

const o = (human: 'pass'|'fail', machine: 'pass'|'fail', runId = Math.random().toString()) =>
  ({ runId, human, machine });

describe('alignment scoring', () => {
  it('agreement is fraction of matching verdicts', () => {
    expect(agreement([o('pass','pass'), o('fail','fail'), o('pass','fail')])).toBeCloseTo(2/3);
  });
  it('kappa is ~1 for perfect, non-trivial agreement', () => {
    expect(cohensKappa([o('pass','pass'), o('fail','fail'), o('pass','pass'), o('fail','fail')]))
      .toBeCloseTo(1, 5);
  });
  it('kappa penalises an always-pass judge on an imbalanced set', () => {
    // 13 pass / 1 fail, judge always passes -> 92.8% agreement but kappa 0
    const out = [...Array(13)].map(() => o('pass','pass')).concat([o('fail','pass')]);
    expect(agreement(out)).toBeGreaterThan(0.9);
    expect(cohensKappa(out)).toBeCloseTo(0, 5);
  });
  it('per-judge FP/FN counts split correctly', () => {
    const results = [
      { judgeId: 'j1', runId: 'a', fired: true,  evidence: null, confidence: null },
      { judgeId: 'j1', runId: 'b', fired: false, evidence: null, confidence: null },
    ];
    const human = { a: 'pass' as const, b: 'fail' as const };
    expect(perJudgeCounts(results, human)).toEqual({ j1: { fp: 1, fn: 1 } });
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm test -- alignment`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement scoring**

`src/lib/alignment/score.ts`:
```typescript
export type RunOutcome = { runId: string; human: 'pass'|'fail'; machine: 'pass'|'fail' };

export function agreement(o: RunOutcome[]): number {
  if (o.length === 0) return 1;
  return o.filter(x => x.human === x.machine).length / o.length;
}

export function cohensKappa(o: RunOutcome[]): number {
  const n = o.length;
  if (n === 0) return 1;
  const po = agreement(o);
  const hFail = o.filter(x => x.human === 'fail').length / n;
  const mFail = o.filter(x => x.machine === 'fail').length / n;
  const pe = hFail * mFail + (1 - hFail) * (1 - mFail);
  if (pe === 1) return po === 1 ? 1 : 0;
  return (po - pe) / (1 - pe);
}

export function perJudgeCounts(
  results: { judgeId: string; runId: string; fired: boolean }[],
  humanByRun: Record<string, 'pass'|'fail'>,
): Record<string, { fp: number; fn: number }> {
  const acc: Record<string, { fp: number; fn: number }> = {};
  for (const r of results) {
    const h = humanByRun[r.runId];
    acc[r.judgeId] ??= { fp: 0, fn: 0 };
    if (r.fired && h === 'pass') acc[r.judgeId].fp++;
    if (!r.fired && h === 'fail') acc[r.judgeId].fn++;
  }
  return acc;
}
```
Add `scoreAlignment` assembling `AlignmentReport` (agreement, kappa, disagreements = outcomes where `human !== machine`, perJudge).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- alignment`
Expected: PASS (all 4, including the κ degenerate-judge guard).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: alignment scoring with Cohen's kappa and per-judge FP/FN"
```

---

# PHASE 3 — Agents and the thin vertical slice

> The spec's top risk mitigation: **prove one failure mode end to end — seeded critiques → clustering → synthesis → alignment — before building the six screens.** Tasks 13–15 build the three agents; Task 16 is the vertical-slice harness that validates them against the real fixtures. Do not start Phase 4 screens until Task 16 is green.

### Task 13: Clustering agent (taxonomy from labels)

**Files:**
- Create: `src/lib/agents/clustering.ts`, `tests/agents/clustering.contract.test.ts`

**Interfaces:**
- Consumes: `streamOpus`, all 34 labels.
- Produces:
  - `type ProposedMode = { name: string; description: string; member_run_ids: string[] }`
  - `clusterLabels(labels: Label[], onReasoning?: (t: string) => void): Promise<ProposedMode[]>` — Opus reads **all 34 labels** (unsupervised; no leakage), streams reasoning, and returns a JSON taxonomy validated by a zod schema `proposedTaxonomySchema`.
  - The prompt must **not** name the five planted modes; it asks the model to discover clusters from critique text alone.

- [ ] **Step 1: Write the failing contract test**

`tests/agents/clustering.contract.test.ts` (validates the parser/zod contract, not a live call — mock `streamOpus`):
```typescript
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/lib/agents/client', () => ({
  streamOpus: vi.fn(async () => JSON.stringify({ modes: [
    { name: 'Wrong info about leave', description: 'x', member_run_ids: ['run-003'] },
  ]})),
}));

describe('clustering contract', () => {
  it('parses a valid taxonomy payload', async () => {
    const { clusterLabels } = await import('@/lib/agents/clustering');
    const modes = await clusterLabels([] as any);
    expect(modes[0].member_run_ids).toEqual(['run-003']);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- clustering`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the clustering agent**

`src/lib/agents/clustering.ts`: define `proposedTaxonomySchema = z.object({ modes: z.array(z.object({ name, description, member_run_ids: z.array(z.string()) })) })`. Build a system prompt instructing Opus to group critiques by the underlying problem the labeller described, to prefer a small number of coherent clusters, and to place a critique in exactly one cluster. Serialize the 34 labels (run_id + verdict + critique). Call `streamOpus`, extract the JSON block, `parse`, return `modes`.

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `npm test -- clustering`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: clustering agent deriving a taxonomy from labels"
```

---

### Task 14: Synthesis agent (one judge per ratified mode)

**Files:**
- Create: `src/lib/agents/synthesis.ts`, `tests/agents/synthesis.contract.test.ts`

**Interfaces:**
- Consumes: `streamOpus`, `astSchema`, a ratified mode + its member critiques from the **build set only**.
- Produces:
  - `synthesizeJudge(mode, buildLabels, onReasoning?): Promise<{ kind: 'llm'|'dsl'; spec: string | AstNode; rationale: string }>` — Opus decides LLM vs DSL **itself** (mapping never hardcoded). If it returns `kind: 'dsl'`, the `spec` is parsed through `astSchema` and re-prompted once if invalid; if `kind: 'llm'`, `spec` is the judge prompt string.
  - Reads only build-set critiques for the mode (holdout stays unseen).

- [ ] **Step 1: Write the failing contract test**

`tests/agents/synthesis.contract.test.ts` — mock `streamOpus` to return a DSL judge and assert the AST is validated:
```typescript
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/lib/agents/client', () => ({
  streamOpus: vi.fn(async () => JSON.stringify({
    kind: 'dsl', rationale: 'deterministic arithmetic check',
    spec: { op: 'compare', cmp: 'neq',
      left:  { op: 'accessor', step: { kind: 'tool_result', tool: 'leave_balance' }, path: 'days_remaining' },
      right: { op: 'accessor', step: { kind: 'final_answer' }, path: 'stated_days' } },
  })),
}));

describe('synthesis contract', () => {
  it('returns a validated DSL judge', async () => {
    const { synthesizeJudge } = await import('@/lib/agents/synthesis');
    const j = await synthesizeJudge({ name: 'm', description: 'd', member_run_ids: [] } as any, []);
    expect(j.kind).toBe('dsl');
    expect((j.spec as any).op).toBe('compare');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- synthesis`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the synthesis agent**

`src/lib/agents/synthesis.ts`: system prompt describes the two judge kinds and the DSL node vocabulary (accessor/literal/compare/exists/notExists/and/or/not/contains) with the trace shape, and asks Opus to choose the kind that best fits the mode — deterministic/structural → DSL, semantic/judgement → LLM — and to justify the choice in `rationale`. On `dsl`, run `astSchema.safeParse`; if it fails, re-prompt once appending the zod error, then throw if still invalid. Return `{ kind, spec, rationale }`.

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `npm test -- synthesis`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: synthesis agent producing LLM or DSL judges"
```

---

### Task 15: Misalignment agent (typed improvement proposals)

**Files:**
- Create: `src/lib/agents/misalignment.ts`, `tests/agents/misalignment.contract.test.ts`

**Interfaces:**
- Consumes: `streamOpus`; for each holdout disagreement — the trace, human verdict + critique, judge verdict + evidence, and for DSL judges the full `EvalResult` binding trace.
- Produces:
  - `type ProposalType = 'narrow'|'broaden'|'adjust'|'split'|'merge'|'label_inconsistency'`
  - `type Proposal = { type: ProposalType; targetJudgeId: string | null; payload: unknown; motivating_run_ids: string[]; explanation: string }`
  - `proposeImprovements(input: MisalignmentInput, onReasoning?): Promise<Proposal[]>` — validated by `proposalsSchema`. `split`/`merge` payloads name affected taxonomy modes (they amend Gate 1); `adjust` payloads carry a replacement AST (validated via `astSchema`); `label_inconsistency` payloads carry the contradicting run pair.

- [ ] **Step 1: Write the failing contract test**

`tests/agents/misalignment.contract.test.ts` — mock `streamOpus`, assert the five+one proposal types parse and that an `adjust` proposal's AST is validated:
```typescript
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/lib/agents/client', () => ({
  streamOpus: vi.fn(async () => JSON.stringify({ proposals: [
    { type: 'label_inconsistency', targetJudgeId: null,
      payload: { run_a: 'run-005', run_b: 'run-021' },
      motivating_run_ids: ['run-005','run-021'], explanation: 'contradictory labels' },
  ]})),
}));

describe('misalignment contract', () => {
  it('parses typed proposals', async () => {
    const { proposeImprovements } = await import('@/lib/agents/misalignment');
    const p = await proposeImprovements({ disagreements: [] } as any);
    expect(p[0].type).toBe('label_inconsistency');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- misalignment`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the misalignment agent**

`src/lib/agents/misalignment.ts`: define `proposalsSchema`. System prompt: explains each proposal type and its effect (`narrow`/`broaden` edit an LLM prompt; `adjust` changes a DSL comparison/threshold/accessor; `split`/`merge` amend the taxonomy; `label_inconsistency` flags contradictory human labels — **human labels are evidence, not infallible truth**). Emphasize that DSL binding traces let it diagnose stale/mis-targeted accessors precisely. Serialize each disagreement (trace, human verdict+critique, judge verdict+evidence, binding trace when present). Parse and validate; for `adjust` payloads run `astSchema.safeParse` on the new AST.

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `npm test -- misalignment`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: misalignment agent producing typed improvement proposals"
```

---

### Task 16: Vertical-slice validation harness (RISK GATE)

> Proves the pipeline end to end on real fixtures before any screen is built. Runs live Opus/Haiku calls, so it is an opt-in script guarded by `ANTHROPIC_API_KEY`, plus a deterministic offline assertion on the DSL path.

**Files:**
- Create: `scripts/vertical-slice.ts`, `tests/slice/dsl-slice.test.ts`

**Interfaces:**
- Consumes: everything from Phases 1–3.
- Produces: a runnable `scripts/vertical-slice.ts` that, for mode 3 (arithmetic, DSL) and mode 1 (fabricated clause, LLM): clusters the 34 labels → picks the relevant proposed mode → synthesizes a judge from build-set critiques → runs it over the 14 holdout runs → prints agreement + κ. And a fully-offline test asserting a hand-written mode-3 DSL judge scores high alignment against the manifest — no API key required.

- [ ] **Step 1: Write the offline DSL-slice test**

`tests/slice/dsl-slice.test.ts` — build the mode-3 arithmetic AST by hand, run it over the holdout via the interpreter + composite, and compare against manifest-derived human verdicts, asserting `agreement >= 0.85` and `kappa >= 0.6`:
```typescript
import { describe, it, expect } from 'vitest';
import { evaluate } from '@/lib/dsl/interpreter';
import { agreement, cohensKappa } from '@/lib/alignment/score';
import { loadTraces } from '@/fixtures/traces';
import { holdoutRunIds } from '@/lib/split';
import { TRACE_MANIFEST } from '@/fixtures/traces/manifest';
import type { AstNode } from '@/lib/dsl/ast';

const mode3: AstNode = { op: 'compare', cmp: 'neq',
  left:  { op: 'accessor', step: { kind: 'tool_result', tool: 'leave_balance' }, path: 'days_remaining' },
  right: { op: 'accessor', step: { kind: 'final_answer' }, path: 'stated_days' } };

describe('mode-3 DSL vertical slice (offline)', () => {
  it('aligns with human labels on the holdout', () => {
    const traces = loadTraces();
    const outcomes = holdoutRunIds().map(id => {
      const t = traces.find(t => t.run_id === id)!;
      const human = TRACE_MANIFEST.find(m => m.run_id === id)!.planted_modes.includes(3) ? 'fail' : 'pass';
      const machine = evaluate(mode3, t).fired ? 'fail' : 'pass';
      return { runId: id, human: human as 'pass'|'fail', machine: machine as 'pass'|'fail' };
    });
    expect(agreement(outcomes)).toBeGreaterThanOrEqual(0.85);
    expect(cohensKappa(outcomes)).toBeGreaterThanOrEqual(0.6);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- dsl-slice`
Expected: FAIL initially — this surfaces any fixture bugs (a mode-3 run whose numbers accidentally agree, a holdout with no mode-3 example). **Fix the Task 4 fixtures until it passes** — this is the fixture-quality gate.

- [ ] **Step 3: Write the live vertical-slice script**

`scripts/vertical-slice.ts`: guard on `process.env.ANTHROPIC_API_KEY`; run `clusterLabels` → log the taxonomy → for the arithmetic-shaped cluster call `synthesizeJudge` (assert it chose `dsl`) and for the fabricated-clause cluster call `synthesizeJudge` (assert it chose `llm`) → run each judge over the holdout → print agreement/κ. Add an npm script `"slice": "tsx scripts/vertical-slice.ts"` and `tsx` as a dev dependency.

- [ ] **Step 4: Run the live slice (requires key)**

Run: `ANTHROPIC_API_KEY=… npm run slice`
Expected: prints a coherent taxonomy, synthesis chooses DSL for mode 3 and LLM for mode 1, both score respectable alignment. **If synthesis picks the wrong kind, iterate the synthesis prompt (Task 14) and the seeded critiques (Task 5) here** — this is the synthesis-quality gate the spec calls out.

- [ ] **Step 5: Run the full offline suite**

Run: `npm test`
Expected: PASS (all offline tests green).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: vertical-slice validation harness (risk gate)"
```

---

# PHASE 4 — Screens

> Screens 2 (Label) and 5 (Alignment) carry the argument — concentrate effort there. Each screen task ends with a manual acceptance check because these are UI deliverables; wire real data through, not placeholders.

### Task 17: Shared trace rendering — TracePane + source peek

**Files:**
- Create: `src/components/TracePane.tsx`, `src/app/api/trace/[runId]/route.ts`

**Interfaces:**
- Consumes: `Trace`, `getEmployee`, `POLICY`.
- Produces: `<TracePane trace={Trace} highlightStepIndex={number|null} onStepClick={(i)=>void} />` — renders `user_message`, each step (tool_call with args, tool_result with `data`/`error`, assistant text), and the `final_answer`. Tool-result steps expose a "peek source record" toggle showing the *actual* employee record / policy clause so fabrications (mode 1) and wrong-record (mode 2) are catchable by eye. Accepts a `highlightStepIndex` so the AssertionView (Task 21) can scroll/flash a step.

- [ ] **Step 1: Build the component and route**

Implement `TracePane` as a client component. The `GET /api/trace/[runId]` route returns the trace plus resolved source records (`getEmployee` for any looked-up name, matching `POLICY` clauses for any `search_policy` call) so the peek shows ground truth beside what the agent claimed.

- [ ] **Step 2: Manual acceptance check**

Run: `npm run dev`, open a labelling URL. Verify: tool calls/results render, errors are visible, and the source peek shows the real record differing from a fabricated/mis-attributed claim on a mode-1 and a mode-2 run.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: TracePane with tool steps and source-record peek"
```

---

### Task 18: Screen 2 — Label (keyboard-driven) + labels API

**Files:**
- Create: `src/app/label/[runId]/page.tsx`, `src/components/CritiqueForm.tsx`, `src/app/api/labels/route.ts`

**Interfaces:**
- Consumes: `TracePane`, `getOrCreateSession`, `db`.
- Produces:
  - `POST /api/labels` — upserts `{ run_id, verdict, critique }` with `author: 'visitor'` for the current session (unique on `session_id, run_id`).
  - `GET /api/labels` — returns the session's labels + progress counts.
  - `<CritiqueForm />` — verdict pass/fail + freeform critique, **keyboard-driven**: `p`/`f` set verdict, `Enter` submits and advances to the next unlabelled run, focus stays in the critique box.
  - Label page: `TracePane` left, `CritiqueForm` right, progress indicator ("26 seeded + N of ~8 yours").

- [ ] **Step 1: Build the API, form, and page**

Implement the upsert route, the keyboard handlers, and the two-pane layout. On submit, advance to the next unlabelled `run_id` in the build∪holdout set.

- [ ] **Step 2: Manual acceptance check**

Run: `npm run dev`. Label 3–4 runs using only the keyboard; confirm rows persist (re-open shows your verdict), progress advances, and seeded Priya labels are present from the start.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: Screen 2 Label — keyboard-driven verdict + critique"
```

---

### Task 19: Screen 1 — Runs overview + entry point

**Files:**
- Create: `src/app/page.tsx` (replace placeholder), `src/app/api/runs/route.ts`

**Interfaces:**
- Consumes: `loadTraces`, session labels, `SLICE`.
- Produces: `GET /api/runs` returning each run with its label status (seeded/yours/unlabelled) and slice; the Runs screen lists them with label progress and links each to `/label/[runId]`, plus a "continue to taxonomy" CTA gated on a minimum visitor-label count.

- [ ] **Step 1: Build the route and screen**

Render the dataset overview table (run id, short summary, verdict if labelled, author). Bootstrap the session on load (`getOrCreateSession`). Gate the taxonomy CTA on ≥ N visitor labels.

- [ ] **Step 2: Manual acceptance check**

Run: `npm run dev`. First visit creates a session pre-loaded with 26 Priya labels; the table reflects them; the CTA unlocks after labelling.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: Screen 1 Runs overview with label progress"
```

---

### Task 20: Screen 3 — Taxonomy ratification (Gate 1)

**Files:**
- Create: `src/app/taxonomy/page.tsx`, `src/components/TaxonomyCard.tsx`, `src/app/api/taxonomy/route.ts`, `src/app/api/taxonomy/ratify/route.ts`
- Use: `ReasoningStream` (Task 26) for the clustering call.

**Interfaces:**
- Consumes: `clusterLabels`, `db`.
- Produces:
  - `POST /api/taxonomy` — runs `clusterLabels` over all 34 labels (streaming reasoning), persists proposed `taxonomy_modes`.
  - `POST /api/taxonomy/ratify` — applies human edits: approve, rename, **split** one cluster into two, **merge** two clusters. Persists ratified modes with `ratified: true`.
  - `<TaxonomyCard mode member-critiques />` with rename/split/merge controls.
- The deliberately ambiguous cluster (modes 1+2) must be splittable here — that is the point of Gate 1.

- [ ] **Step 1: Build the clustering trigger, cards, and ratify actions**

Render proposed clusters with their member critiques inline. Implement rename (text), split (choose which member critiques go to the new cluster), merge (select two clusters). Save ratified taxonomy.

- [ ] **Step 2: Manual acceptance check**

Run the clustering call; confirm reasoning streams, the modes-1+2 cluster appears lumped, and a manual **split** produces two ratified modes persisted to the session.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: Screen 3 Taxonomy ratification with split/merge (Gate 1)"
```

---

### Task 21: Screen 4 — Evaluator review (Gate 2) + AssertionView

**Files:**
- Create: `src/app/evaluators/page.tsx`, `src/components/EvaluatorCard.tsx`, `src/components/AssertionView.tsx`, `src/app/api/synthesis/route.ts`, `src/app/api/judges/route.ts`

**Interfaces:**
- Consumes: `synthesizeJudge`, `evaluate` (for a preview binding trace), `db`.
- Produces:
  - `POST /api/synthesis` — for each ratified mode, calls `synthesizeJudge` on **build-set** critiques (streaming), persists an unapproved `judge`.
  - `POST /api/judges` — approve / edit / **flip type** a judge; persists `approved: true`.
  - `<AssertionView ast bindingTrace onLeafClick />` — renders a DSL judge as `accessor ⟨value⟩ cmp accessor ⟨value⟩ ✓/✗` with the resolved values bound inline and the source step index beneath each leaf; each leaf is clickable and calls back to scroll the `TracePane` (via `highlightStepIndex`).
  - `<EvaluatorCard />` — shows judge type + agent rationale, the prompt (LLM) or the rendered `AssertionView` (DSL), and approve/edit/flip controls.

- [ ] **Step 1: Build synthesis trigger, cards, AssertionView, and approve/edit/flip**

Render one card per mode. For DSL judges, evaluate against a representative failing run to produce a sample binding trace for `AssertionView`. Editing an LLM judge edits its prompt; editing a DSL judge edits comparator/threshold/accessor; "flip type" re-requests synthesis with the opposite `kind` forced.

- [ ] **Step 2: Manual acceptance check**

Confirm each mode yields a judge with rationale, the DSL card renders bound values with clickable leaves that scroll the trace pane, and approving persists.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: Screen 4 Evaluator review with bound-value AssertionView (Gate 2)"
```

---

### Task 22: Screen 5 — Alignment + live DSL tuning

> The most persuasive interaction in the demo. DSL judges evaluate in microseconds, so alignment recomputes **client-side, live**, as the user edits a threshold/comparator; flipping runs animate in the disagreement list. LLM-judge results are fetched once server-side and held fixed during tuning.

**Files:**
- Create: `src/app/alignment/page.tsx`, `src/components/AlignmentPanel.tsx`, `src/components/LiveTuner.tsx`, `src/app/api/alignment/route.ts`, `src/app/api/alignment/preview/route.ts`

**Interfaces:**
- Consumes: `runLlmJudge`, `evaluate`, `compositeVerdict`, `scoreAlignment`, holdout labels; the DSL interpreter is also imported **into the client bundle** so tuning recomputes without a round-trip.
- Produces:
  - `POST /api/alignment` — runs all approved judges over the 14 holdout runs (LLM via Haiku, DSL via interpreter), returns `AlignmentReport` + each run's per-judge results + DSL binding traces.
  - `<AlignmentPanel />` — agreement % and Cohen's κ headline, per-judge FP/FN, disagreement list.
  - `<LiveTuner judge holdoutTraces humanByRun />` — edit form for a DSL judge that re-runs `evaluate` over the holdout **in the browser** on every change, recomputing `agreement`/`kappa`/`perJudge` instantly and animating runs that flip verdict. A "commit tuning" action persists the edited AST via `POST /api/judges`.
  - `POST /api/alignment/preview` — optional server parity check for a tuned AST (used to verify client math, not on the hot path).

- [ ] **Step 1: Build the scoring route and AlignmentPanel**

Run judges over the holdout server-side; render headline agreement/κ, per-judge FP/FN, and the disagreement list (human verdict + critique vs machine verdict + evidence).

- [ ] **Step 2: Build LiveTuner with client-side recompute**

Hold the LLM-judge results fixed; recompute the DSL judge's contribution + composite + `scoreAlignment` on every edit using the imported interpreter. Animate flipped runs.

- [ ] **Step 3: Manual acceptance check**

Adjust a DSL threshold and confirm agreement/κ update with no network call and flipped runs animate; confirm the κ headline exposes a degenerate all-pass judge.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: Screen 5 Alignment with live client-side DSL tuning"
```

---

### Task 23: Screen 6 — Improvement loop (Gate 3) + holdout accounting

**Files:**
- Create: `src/app/improvement/page.tsx`, `src/components/ProposalCard.tsx`, `src/app/api/improvement/route.ts`, `src/app/api/improvement/apply/route.ts`

**Interfaces:**
- Consumes: `proposeImprovements`, `db`, alignment results, iteration count.
- Produces:
  - `POST /api/improvement` — feeds each holdout disagreement (trace, human verdict+critique, judge verdict+evidence, DSL binding trace) to `proposeImprovements` (streaming), persists typed `proposals`.
  - `POST /api/improvement/apply` — applies edited/approved proposals: `narrow`/`broaden`/`adjust` re-spec the target judge; `split`/`merge` **amend the ratified taxonomy** (reach back to Gate 1) and trigger re-synthesis of affected modes; `label_inconsistency` surfaces the contradicting label pair, asks which the user stands by, updates the label, and re-scores.
  - `<ProposalCard />` — shows type, motivating disagreements, an editable payload, and a freeform recommendation box; apply button.
  - **Holdout accounting:** after the third applied iteration against the same holdout, show the spec's message — *"You've tuned against this holdout three times. Label fresh runs to re-establish a clean measurement."* — and route back to labelling. One `iterations.index >= 3` conditional.

- [ ] **Step 1: Build proposal generation, cards, apply logic, and the 3-iteration gate**

Implement each proposal type's apply path, the freeform recommendation capture (fed into the next re-synthesis prompt), re-synthesis → re-score, and the iteration-3 conditional.

- [ ] **Step 2: Manual acceptance check**

Generate proposals, apply an `adjust`, confirm re-score shows an alignment delta; trigger a `label_inconsistency` and confirm changing the answer updates the label and re-scores; after three iterations confirm the fresh-labels message appears.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: Screen 6 Improvement loop with typed proposals and holdout accounting (Gate 3)"
```

---

### Task 24: Screen 7 — Payoff (evaluator on the 6 unlabelled runs)

**Files:**
- Create: `src/app/payoff/page.tsx`, `src/app/api/payoff/route.ts`

**Interfaces:**
- Consumes: approved judges, `unlabelledRunIds`, `runLlmJudge`, `evaluate`, `compositeVerdict`.
- Produces: `GET/POST /api/payoff` — runs the finished evaluator over the 6 unlabelled runs and returns per-run composite verdict + firing judges + evidence/binding traces. The screen presents these as the payoff: the human-tuned evaluator now judging runs no human labelled.

- [ ] **Step 1: Build the payoff route and screen**

Run the evaluator over the 6 unlabelled runs; render each with its verdict, which judges fired, and their evidence (LLM) or bound assertion (DSL, via `AssertionView`).

- [ ] **Step 2: Manual acceptance check**

Confirm the 6 runs render verdicts consistent with their planted modes and DSL firings show bound values.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: Screen 7 Payoff — evaluator on unlabelled runs"
```

---

# PHASE 5 — Demo polish

### Task 25: Reasoning streaming component + wiring

**Files:**
- Create: `src/components/ReasoningStream.tsx`
- Modify: the taxonomy / synthesis / improvement routes to stream via `ReadableStream`.

**Interfaces:**
- Consumes: `streamOpus`'s `onText` callback.
- Produces: `<ReasoningStream endpoint body />` — opens a streaming fetch to an agent route and renders reasoning tokens live. Agent routes return a `ReadableStream` that forwards `onText` chunks then a final JSON result sentinel.

- [ ] **Step 1: Implement streaming end-to-end for the clustering route, then reuse for synthesis/misalignment**

Convert the three agent routes to stream. `ReasoningStream` appends chunks to a scrollback and swaps to the result view on the sentinel.

- [ ] **Step 2: Manual acceptance check**

Trigger clustering and confirm reasoning appears token-by-token rather than a spinner, then the taxonomy renders.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: stream Opus reasoning to the UI across agent screens"
```

---

### Task 26: Showcase (deep-linkable frozen) session

**Files:**
- Create: `src/lib/session/showcase.ts`, `src/app/api/session/showcase/route.ts`
- Modify: `src/lib/session/index.ts` (recognise a `?showcase=<stage>` deep link).

**Interfaces:**
- Consumes: `db`, cached agent outputs.
- Produces: `getShowcaseSession(stage: 'pre-taxonomy'|'pre-evaluator'|'post-alignment')` — returns a session frozen at the chosen beat, served from **cached** clustering/synthesis/alignment results (no live re-run), so the presenter can jump to any beat and the demo survives bad wifi / a stalled API call.

- [ ] **Step 1: Build the frozen-session fixtures and loader**

Persist one snapshot per stage (labels + taxonomy + judges + alignment as appropriate). Deep link `/?showcase=post-alignment` loads the snapshot read-only.

- [ ] **Step 2: Manual acceptance check**

Open each showcase deep link with no `ANTHROPIC_API_KEY` set; confirm the corresponding screen renders fully from cache.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: deep-linkable showcase sessions served from cache"
```

---

### Task 27: Deploy config, iteration cap, and README

**Files:**
- Create: `vercel.json` (if needed), `README.md`
- Modify: session creation (per-IP rate limit already in Task 8), improvement route (enforce the 3-iteration cap server-side).

**Interfaces:**
- Produces: deploy-ready config, documented env vars (`ANTHROPIC_API_KEY`, `DATABASE_URL`), and a README covering the lifecycle, the split, cost bounds (~$0.70 first pass, ~$1.50 worst case), and the abuse mitigations.

- [ ] **Step 1: Finalize deploy config and docs**

Ensure Neon connection works in Vercel's serverless runtime (`prepare: false` already set). Enforce the iteration cap server-side. Write the README.

- [ ] **Step 2: Full verification**

Run: `npm test && npm run build`
Expected: all tests pass, production build succeeds.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: deploy config, iteration cap, and README"
```

---

## Self-Review

**Spec coverage** — every spec section maps to a task:
- §1 domain/seeded data → Tasks 3, 4 (employees, policy, 40 traces, planted modes, deterministic fields).
- §2 corpus/labels/split → Tasks 5 (26 critiques + ambiguous cluster), 6 (20/14/6 split), 8 (label schema, Priya seed).
- §3 screens 1–7 → Tasks 17–24.
- §4 judge execution (LLM Haiku, DSL AST/zod/interpreter/binding trace, live tuning) → Tasks 9, 10, 11, 21, 22.
- §5 alignment (agreement, Cohen's κ, per-judge FP/FN) → Task 12.
- §6 improvement loop (typed proposals, split/merge amend taxonomy, label_inconsistency, 3-iteration accounting) → Task 23.
- §7 session model (ephemeral cookie session, Priya seed, showcase) → Tasks 8, 26.
- §8 stack/models/streaming/cost → Tasks 1, 7, 11, 25, 27.
- §9 risks (seeded critiques, synthesis quality, vertical slice first) → Tasks 5, 14, 16.
- §10 out of scope → honored (no live agent execution, no auth, no cross-visitor corpora, no generated-code judges — DSL only).

**Placeholder scan** — engine tasks (9–12) carry complete, runnable code and TDD cycles. Fixture/agent/screen tasks specify exact interfaces, zod contracts, key logic, and explicit manual acceptance criteria rather than "add error handling."

**Type consistency** — `evaluate → EvalResult` (Task 10) is consumed by Tasks 21/22/23 under that name; `JudgeResult`/`compositeVerdict` (Task 11) feed Task 12's `perJudgeCounts` and Task 22; `AstNode`/`astSchema`/`parseAst` (Task 9) are consumed by Tasks 10, 14, 15, 21, 22; `ProposedMode`/`Proposal`/`ProposalType` names are stable across Tasks 13/15/20/23.

---

## Execution Handoff

Plan complete and saved to `human-driven-evals/docs/superpowers/plans/2026-07-24-human-driven-evals.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
