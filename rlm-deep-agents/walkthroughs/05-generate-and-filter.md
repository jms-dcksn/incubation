# 05 — Generate and filter

**Source:** [`examples/generate_and_filter.py`](../src/rlm_deep_agents/examples/generate_and_filter.py)
· **Run:** `uv run rlm-generate`

> Multiple subagents generate independent solutions to the same problem. The agent
> compares, scores, and filters the results in code, keeping only the best.

**Reach for it when:** exploring several options beats committing to one — design
proposals, refactoring strategies, content variations.

## What we configure

A single generator role, invoked several times to get *independent* attempts:

```python
SUBAGENTS = [
    {
        "name": "architect",
        "description": "Proposes a rate-limiter design with an explicit tradeoff analysis.",
        "system_prompt": "... propose ONE concrete rate-limiter design ... be honest about weaknesses.",
    }
]
```

The task is to design a rate limiter given concrete requirements (100 req/min per
key, correct under bursts, multi-instance, low complexity).

## What we ask

```
1. Dispatch THREE `architect` subagents in parallel, each an independent design
   (nudge toward token-bucket / sliding-window / fixed-window so they differ).
2. Score each in code: correctness under burst, multi-instance support,
   operational simplicity (0-3 each).
3. Return the winner, the score breakdown for all three, and a rationale.
```

## What the agent writes

Generate in parallel, then **score and sort in code** — the selection is
deterministic, not another vibe-based model call:

```javascript
// Generate independent proposals in parallel
const proposals = await Promise.all(
  [1, 2, 3].map((n) =>
    task({
      description: `Approach ${n}: design the rate limiter, with tradeoffs.`,
      subagentType: "architect",
      responseSchema: designSchema,   // -> { design, algorithm, burst, multiInstance, tradeoffs }
    })
  )
);

// Score each against the requirements, then keep the best
function score(p) {
  return burstScore(p) + multiInstanceScore(p) + simplicityScore(p);
}
const ranked = proposals.map((p) => ({ p, s: score(p) }))
                        .sort((a, b) => b.s - a.s);
ranked[0].p;   // the winner; ranked carries the full breakdown
```

## Why this matters

- **Independent samples, not one hedged answer.** Three separate `architect`
  dispatches explore genuinely different regions of the design space. Asking one
  model for "the best design" collapses that exploration into a single guess.
- **Scoring is explicit and inspectable.** The criteria (burst, multi-instance,
  simplicity) live in code you can read and tweak. You keep the *why*, not just
  the winner.
- **Generation and evaluation are decoupled.** You can change how many candidates
  you generate, or how you score them, without touching the generator prompt.

## Generate-and-filter vs. tournament

Both explore multiple options. The difference is how you choose:

- **Generate and filter** scores each candidate **absolutely** against fixed
  criteria, then sorts. Best when you can articulate a rubric.
- **[Tournament](./06-tournament.md)** compares candidates **relatively**,
  head-to-head. Best when "which of these two is better?" is easier to answer than
  "score this one out of 10."
