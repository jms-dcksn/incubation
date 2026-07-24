# Human-Driven Evals — Design

**Date:** 2026-07-20
**Status:** Approved, ready for planning

## Premise

Great evals start with human intuition, not with an LLM analyzing traces. This is a publicly-deployed demo of an evaluation harness where a human labels real agent runs, an analysis agent derives a failure taxonomy from those labels, the human ratifies it, evaluators are synthesized per ratified failure mode, and alignment against held-out human labels drives an improvement loop.

The argument the demo makes: **automated analysis assists, humans decide.** Every automated step is followed by a human gate.

## Lifecycle

1. Runs exist (pre-baked production traffic)
2. Human labels runs — verdict + freeform critique
3. Clustering agent derives a failure taxonomy from the labels
4. **Gate 1:** human ratifies the taxonomy (approve / rename / split / merge)
5. Synthesis agent produces one judge per ratified mode, choosing LLM or code implementation
6. **Gate 2:** human approves each judge — its type, its prompt or assertion
7. Judges run against held-out labels; alignment scored
8. Misalignment agent proposes typed edits
9. **Gate 3:** human reviews proposals, adds their own recommendations, applies
10. Re-score; after three iterations against the same holdout, prompt for fresh labels

---

## 1. Domain and seeded data

**HR leave & benefits assistant.** Chosen because a stranger with no domain knowledge can tell right from wrong in under 30 seconds — the binding constraint for a public demo where visitors do the labelling.

Static dataset:
- ~30 employee records: name, tenure, location, employment type, accrued leave, remaining balance
- ~15-clause policy handbook: parental leave, carry-over caps, jurisdiction-specific entitlements, notice periods

Agent tools: `lookup_employee(name)`, `search_policy(query)`.

**40 pre-baked traces**, generated offline and hand-curated, committed as JSON fixtures. ~35% exhibit at least one failure.

### Planted failure modes

| # | Mode | Deterministically checkable? |
|---|---|---|
| 1 | Fabricated policy clause — cites a rule absent from the handbook | No |
| 2 | Right policy applied to the wrong employee record | No |
| 3 | Arithmetic error on accrued/remaining balance | **Yes** |
| 4 | Swallowed tool error — tool returned an error, agent answered confidently | **Yes** |
| 5 | Premature closure — "you're all set" without addressing the question | No |

Each mode appears across multiple runs so the clustering agent has structure to find. The synthesis agent must *arrive* at the LLM/code split on its own — the prompt is designed for it, but the mapping is not hardcoded.

---

## 2. Corpus, labels, and the split

| Slice | Count | Purpose |
|---|---|---|
| Pre-seeded labels ("Priya, QA lead") | 26 | Realistic prior labelling effort |
| Visitor labels | ~8 | What the visitor contributes |
| **Total labelled** | **34** | |
| → Judge synthesis (build set) | 20 | |
| → Alignment scoring (holdout) | 14 | |
| Unlabelled | 6 | Final payoff view |

**Taxonomy clustering reads all 34 labels.** It is unsupervised structure discovery and its output is human-ratified, so there is nothing to leak. Only *judge synthesis* is restricted to the build set.

### Label schema

```
{ run_id, verdict: pass|fail, critique: string, author: 'priya'|'visitor' }
```

No tags, no categories, no checklist at label time. Structure is derived downstream and ratified by the human. This is the core of the thesis — nothing is imposed on the labeller.

### The seeded critiques

**This is the highest-effort, highest-risk asset in the build.** 26 critiques that read as genuinely human, vary in phrasing and length, and cluster into four clean groups plus **one deliberately ambiguous cluster**.

The planned ambiguity: modes 1 (fabricated clause) and 2 (wrong employee record) both read as *"it told me something untrue about my leave"* in casual critique phrasing. The clustering agent should lump them; a human should split them. That is what makes Gate 1 a real judgement rather than a rubber stamp.

**Write these early and iterate against the actual clustering agent.** They are not late-stage content fill — screens 3 through 6 all degrade if they are wrong.

---

## 3. Screens

| # | Screen | Purpose |
|---|---|---|
| 1 | Runs | Dataset overview, label progress, entry point |
| 2 | **Label** | Trace left, verdict + critique right. Keyboard-driven. Tool calls, tool results, and a peek at the underlying source record so fabrications are catchable. |
| 3 | Taxonomy ratification | Proposed clusters with member critiques; approve / rename / split / merge |
| 4 | Evaluator review | One card per mode: proposed judge type + agent's rationale, the prompt or rendered assertion; approve / edit / flip type |
| 5 | **Alignment** | Agreement + Cohen's κ headline, per-judge FP/FN, disagreement list, live tuning for DSL judges |
| 6 | Improvement | Typed proposals with motivating disagreements, plus freeform recommendation box |
| 7 | Payoff | Evaluator running on the 6 unlabelled runs |

**Screens 2 and 5 carry the argument.** Concentrate build effort there.

---

## 4. Judge execution

Composite run verdict: **fail if any judge fires.** Alignment computed per-judge and overall.

### LLM judges

Model: `claude-haiku-4-5`. One call per (judge × run). Returns verdict, evidence span, confidence.

### DSL judges

The synthesis agent emits an **AST as JSON**, validated by zod — not code as a string. No parsing step, no malformed-output failure mode, and **no code execution surface at all**.

Node types (~6):

| Node | Purpose |
|---|---|
| `accessor` | Step selector + field path |
| `literal` | Constant, with optional numeric tolerance |
| `compare` | `eq` / `neq` / `gt` / `lt` / `gte` / `lte` |
| `exists` / `notExists` | Presence checks |
| `and` / `or` / `not` | Composition |
| `contains` | String / set membership (citation-in-source) |

Example:

```json
{ "op": "compare", "cmp": "eq",
  "left":  { "op": "accessor", "step": {"kind":"tool_result","tool":"leave_balance"},
             "path": "days_remaining" },
  "right": { "op": "accessor", "step": {"kind":"final_answer"},
             "path": "stated_days" } }
```

The interpreter (~200 lines) evaluates against the trace JSON and records a **binding trace**: every accessor resolved, the value obtained, the source step index, and the result of each comparison.

The UI renders assertions with resolved values bound inline:

```
leave_balance.days_remaining  ⟨14⟩   ==   final_answer.stated_days  ⟨12⟩   ✗
        ↑ step 3                                    ↑ step 7
```

Each leaf is clickable and scrolls the trace pane to the step it read from.

### Live tuning (screen 5)

Because DSL judges evaluate in microseconds, **alignment recomputes live**. The user adjusts a threshold or flips a comparison in the edit form and the score across all 14 holdout runs updates instantly, with runs that flip verdict animating in the list beside it.

This is impossible with LLM judges (14 calls per adjustment, seconds of latency, real cost) and free with the DSL. It is the most persuasive interaction in the demo because it makes human-in-the-loop tuning tactile rather than a form submission.

---

## 5. Alignment scoring

Computed on the **14 holdout runs only**.

- **Agreement %** — headline number, demo-legible
- **Cohen's κ** — displayed alongside; guards against the degenerate "always pass" judge scoring ~65% and looking respectable. Four lines of code; immunises the demo against the first sharp question anyone asks.
- **Per-judge false-positive / false-negative counts** — drives the improvement loop

---

## 6. Improvement loop

The misalignment agent consumes, for each holdout disagreement: the trace, human verdict + critique, judge verdict + evidence, and — for DSL judges — the full binding trace. That last input lets it diagnose rather than guess: *"this rule read `days_remaining` from step 3, but on these four runs the balance updated at step 5, so it compared a stale value."*

### Proposal types

| Type | Effect |
|---|---|
| `narrow` / `broaden` | Adjust an LLM judge's prompt |
| `adjust` | Change a DSL comparison, threshold, or accessor |
| `split` | Ratified mode was too coarse — **amends the taxonomy** |
| `merge` | Two modes are one — **amends the taxonomy** |
| `label_inconsistency` | Two human labels contradict each other on materially identical behaviour |

Split and merge reach back to Gate 1, not just forward to the judges — the loop is not linear.

`label_inconsistency` treats human labels as **evidence rather than infallible ground truth**. Sometimes the judge is right and the human was inconsistent; the agent surfaces the contradicting pair and asks which the user stands by. Changing the answer updates the label and re-scores. Inter-annotator inconsistency is the central practical problem in human eval — a demo that pretends otherwise argues something weaker than it could.

Each proposal shows its motivating disagreements. The user reviews, edits, adds freeform recommendations, applies. Then re-synthesis → re-score → alignment delta.

### Honest holdout accounting

Each iteration re-scores against the same 14 runs, so by iteration three the evaluator is overfitting to them. After three rounds the system says so:

> *"You've tuned against this holdout three times. Label fresh runs to re-establish a clean measurement."*

One conditional to implement. It gives the lifecycle a circular ending — back to labelling — rather than terminating in a green checkmark.

---

## 7. Session model

**Fresh ephemeral session per visitor.** Cookie-keyed, server-side row, no auth. Arrives pre-seeded with Priya's 26 labels; the visitor adds ~8.

This solves two problems at once: the on-stage time problem (nobody labels 34 runs during a pitch) and the garbage-critique problem (one visitor typing "bad" eight times cannot poison a corpus that is 76% good material). It also buys a narrative beat — the visitor *joins* a labelling effort in progress, which is what happens on a real team.

**Showcase session:** a deep-linkable session frozen at a chosen stage — pre-taxonomy, pre-evaluator, or post-alignment. Lets the presenter jump to whichever beat the room needs, and rescues the demo if wifi is bad or an API call stalls mid-pitch.

---

## 8. Stack

- Next.js App Router on Vercel
- Postgres (Neon) + Drizzle
- Anthropic SDK
- No auth; cookie-keyed session rows

### Models

| Use | Model | Rationale |
|---|---|---|
| LLM judges | `claude-haiku-4-5` | High call volume, short traces, simple verdict task |
| Clustering, synthesis, misalignment | `claude-opus-4-8` | Reasoning-heavy; quality is visible on screen |

Opus 4.8 calls use `thinking: {type: "adaptive"}` with `output_config: {effort: "high"}`. Haiku 4.5 judges run without thinking.

**Long-running agent calls stream their reasoning to the UI** rather than showing a spinner. Better demo material than a progress bar and less work than a background-job queue.

### Cost per completed visitor

An evaluator execution covers the 14 holdout runs plus the 6 unlabelled payoff runs = 20 runs. Of 5 judges, ~3 are LLM judges (modes 1, 2, 5) and ~2 are DSL judges (modes 3, 4) which cost nothing to run.

| Component | Calls | Estimate |
|---|---|---|
| LLM judges: 3 × 20 runs on Haiku 4.5 | 60 | ~$0.17 |
| DSL judges | 0 | $0 |
| Clustering + synthesis + misalignment on Opus 4.8 | 3 | ~$0.50 |
| **First pass through the flow** | | **~$0.70** |
| Worst case with 3 improvement iterations | | **~$1.50** |

*Correction to an earlier in-conversation estimate of "a cent or two" — that was wrong by roughly two orders of magnitude.* Bounded, but not free. Mitigations: rate-limit session creation per IP, cap improvement iterations at 3, and serve the showcase session from cached results rather than re-running.

---

## 9. Risks

**Seeded critiques are load-bearing and hard.** 26 human-sounding critiques that cluster into four clean groups plus one genuine ambiguity. Get them wrong and screens 3–6 all degrade. Mitigation: write them first, iterate against the real clustering agent, treat the ambiguous cluster as a designed artifact rather than an accident.

**Judge synthesis quality is unproven until built.** The design assumes an Opus call can take a ratified failure mode plus its member critiques and produce a genuinely decent judge. Likely, but it is the one place where the demo could be structurally sound and still feel weak.

**Mitigation for both: build a thin vertical slice first** — one failure mode, end to end, seeded critiques through synthesis through alignment — before building the remaining six screens.

## 10. Explicitly out of scope

- Live agent execution (traces are pre-baked; the agent is not the interesting part)
- Authentication and user accounts
- Shared or cross-visitor label corpora
- Persisting evaluators beyond the session
- Generated-code judges (the DSL covers the deterministic modes with no execution surface)
