# 06 — Tournament

**Source:** [`examples/tournament.py`](../src/rlm_deep_agents/examples/tournament.py)
· **Run:** `uv run rlm-tournament`

> Variations are compared head-to-head by a judge subagent, with winners advancing
> through elimination rounds.

**Reach for it when:** the criteria are subjective or *relative* — style
selection, optimization under fuzzy goals, choosing between competing
implementations where "A or B?" is easier than an absolute score.

## What we configure

A generator and a judge:

```python
SUBAGENTS = [
    {
        "name": "writer",
        "description": "Rewrites a function for readability and clarity.",
        "system_prompt": "... rewrite to maximize readability while preserving behavior ...",
    },
    {
        "name": "judge",
        "description": "Compares two implementations and picks the more readable one.",
        "system_prompt": "... pick the more readable, correct one. Return exactly 'A' or 'B' ...",
    },
]
```

The input is a deliberately messy `createOrder` function. Several `writer`s
propose rewrites; the `judge` runs the bracket.

## What we ask

```
1. Dispatch FOUR `writer` subagents in parallel (nudge toward different
   priorities: early returns, helpers, immutability, naming).
2. Run a single-elimination bracket: pair candidates, `judge` picks each winner,
   advance winners, repeat until one remains.
3. Return the champion and the judge's reasoning per round.
```

## What the agent writes

The bracket is a `while` loop in interpreter code; the `judge` subagent only ever
answers one small question — "which of these two?":

```javascript
// Generate variants in parallel
let bracket = await Promise.all(
  [1, 2, 3, 4].map((n) =>
    task({ description: `Rewrite createOrder for readability (variant ${n}).`, subagentType: "writer" })
  )
);

// Pairwise elimination until a single champion remains
while (bracket.length > 1) {
  const winners = [];
  for (let i = 0; i < bracket.length; i += 2) {
    if (bracket[i + 1] === undefined) { winners.push(bracket[i]); break; }  // odd one out gets a bye
    const { winner } = await task({
      description: `Pick the more readable:\n\nA:\n${bracket[i]}\n\nB:\n${bracket[i + 1]}`,
      subagentType: "judge",
      responseSchema: pickSchema,   // -> { winner: "A" | "B" }
    });
    winners.push(winner === "A" ? bracket[i] : bracket[i + 1]);
  }
  bracket = winners;
}
bracket[0];   // the winning rewrite
```

## Why this matters

- **Relative judgement is easier and more reliable.** Models are better at "is A
  or B more readable?" than at "rate A's readability 7.5/10." The tournament only
  ever asks the easy question.
- **The bracket structure is code.** Pairing, byes for odd counts, and advancing
  winners are all handled by the loop — deterministically — round after round. The
  model isn't asked to remember who's still in.
- **It scales logarithmically.** N candidates resolve in ⌈log₂ N⌉ rounds of
  pairwise comparisons.

## Variations

- **Best-of-three per match** to dampen judge noise: dispatch the `judge` three
  times per pair and take the majority.
- **Swiss / round-robin** instead of single elimination when you want a full
  ranking, not just a champion — same idea, different loop.
- See [generate-and-filter](./05-generate-and-filter.md) for the absolute-scoring
  alternative.
