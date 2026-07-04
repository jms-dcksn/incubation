# 07 — Loop until done

**Source:** [`examples/loop_until_done.py`](../src/rlm_deep_agents/examples/loop_until_done.py)
· **Run:** `uv run rlm-loop`

> The agent runs a discovery loop, deduplicating against what it has already
> found, until no new results appear. Useful when the scope of the work is not
> known upfront.

**Reach for it when:** you want *completeness* rather than a fixed number of
results and you don't know the scope in advance — exhaustive search, dead-code
detection, dependency audits.

## What we configure

One `analyzer` subagent that is explicitly told what's already been found, so it
only reports *new* things:

```python
SUBAGENTS = [
    {
        "name": "analyzer",
        "description": "Finds unused exports, unreachable functions, and dead code paths.",
        "system_prompt": (
            "... Given the code and a list of what has already been found, find "
            "ADDITIONAL dead code only ... If there is nothing new, return an "
            "empty list."
        ),
    }
]
```

The sample code has **layered** dead code: `orphan()` is obviously unused, but
`legacyFormat()` only *looks* reachable until you notice its single caller
(`legacyExport()`) is itself never imported. One pass tends to catch the first
layer; the loop keeps going until a pass adds nothing.

## What we ask

```
1. Repeatedly dispatch `analyzer`, passing the ids already found so it reports
   only NEW dead code.
2. Deduplicate against what's collected (by id).
3. Stop when a round returns nothing new (convergence).
4. Return the consolidated list + how many passes it took.
```

## What the agent writes

The loop, the dedup set, and the **termination condition** all live in interpreter
code — the model doesn't have to decide "am I done?" by feel:

```javascript
const seen = new Set();
const found = [];
let passes = 0;

while (true) {
  passes++;
  const { items } = await task({
    description: `Find dead code. Already found: ${[...seen].join(", ") || "(none)"}.`,
    subagentType: "analyzer",
    responseSchema: itemsSchema,   // -> { items: [{ id, file }] }
  });

  const fresh = items.filter((i) => !seen.has(i.id));
  if (fresh.length === 0) break;   // converged: a whole pass found nothing new
  for (const i of fresh) { seen.add(i.id); found.push(i); }
}

({ found, passes });
```

## Why this matters

- **Termination is a structural guarantee.** The loop stops when — and only when —
  a full pass surfaces nothing new. A turn-by-turn agent, by contrast, stops when
  it *feels* done, which for "find everything" is exactly the wrong instinct.
- **Deduplication is exact.** The `seen` set makes "have we already found this?" a
  hash lookup, not a fuzzy recollection. Passing `seen` back into each dispatch
  also steers the subagent toward genuinely new ground.
- **Scope is discovered, not assumed.** You never told the agent how many issues
  exist. It keeps looking until the search itself says it's exhausted.

## Variations

- **Safety cap.** Add `if (passes >= MAX) break;` to bound cost when convergence
  might be slow or the subagent is flaky.
- **Frontier expansion.** Instead of re-scanning everything, feed each pass the
  *new* items as seeds (crawl-style) — same converge-when-empty condition.
