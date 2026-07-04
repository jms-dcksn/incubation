# 08 — RLM long-context aggregation (OOLONG-style)

**Source:** [`examples/rlm_long_context.py`](../src/rlm_deep_agents/examples/rlm_long_context.py)
· **Run:** `uv run rlm-longcontext`

This is the flagship of the **"How to Use RLMs in Deep Agents"** post. Everything
before it was an *orchestration* pattern; this one is about **fighting context
rot on long inputs** — the specific problem RLMs were designed for.

> The more context agents accumulate, the worse they perform due to a phenomenon
> called context rot. RLMs address this: instead of working turn by turn or
> relying on lossy summarization, the model runs code in a REPL that dispatches
> subagents and recurses over pieces of the input context.

## The problem

> Consider an agent finding the average deal size across 10,000 sales call
> transcripts. Turn by turn, the model has to track a running total in its own
> context, and that total risks drift the longer it counts.

We reproduce this with an **OOLONG-style** task (from the LangChain benchmark
run): thousands of news headlines, each with a `user` and a `date` but **no
visible category**. To answer a question you have to classify every headline into
one of four topics — world / sports / business / sci_tech — and then aggregate
across the entire set:

| Question type | What it requires | Example |
| --- | --- | --- |
| Counting | Scan all rows, count by category | How many world headlines are there? |
| User | Filter by user, then count | For user 72341, how many sci/tech headlines? |
| Temporal | Filter by date, then count | Before Aug 2004, was sports more common than world? |

At long context lengths, a plain agent doesn't just get the count *slightly*
wrong — the blog's 128k run shows it often **gives up outright**, saying it can't
compute the result. The RLM harness kept working (0.79 vs 0.44 in that run).

## The RLM move

Keep the **data** and the **counting** in interpreter variables and code. Use
subagents only for the judgement-heavy part — classifying a *slice* of headlines —
and never ask the model to hold a running total in its head.

## What we configure

A single `classifier` subagent that labels a batch of headlines:

```python
SUBAGENTS = [
    {
        "name": "classifier",
        "description": "Classifies a batch of headlines into world/sports/business/sci_tech.",
        "system_prompt": (
            "... For EACH headline assign exactly one category ... Return an "
            "array aligned to input order ... Do not skip any item ..."
        ),
    }
]
```

The dataset comes from
[`sample_data.make_headlines`](../src/rlm_deep_agents/sample_data.py), which
deterministically generates rows *and* keeps a hidden `_category` so we can
compute the **ground truth** in plain Python and check the agent's answer:

```python
rows  = make_headlines(240)
truth = expected_counts(rows)   # {'world': 60, 'sports': 60, 'business': 60, 'sci_tech': 60}
```

The agent, of course, only receives the headlines with the category **stripped**
(`headlines_as_json`) — it has to recover the counts itself.

## What we ask

The prompt spells out the RLM shape explicitly — *keep counting in code, classify
in batches*:

```
IMPORTANT: keep the dataset and all counting in interpreter variables and code.
Do not try to hold running totals in your own reasoning.

1. Parse the JSON into an interpreter variable `rows`.
2. Split `rows` into batches (e.g. 30 per batch).
3. For each batch, dispatch a `classifier` subagent that labels every headline.
   Run batches in parallel.
4. Merge the labels back onto the rows in code.
5. Compute, entirely in code: counts per category; sci_tech count for user 72341;
   whether sports > world before 2004-08-01.
```

## What the agent writes

The data lives in a variable, classification is fanned out over slices, and the
aggregation is a plain `reduce` — the model never counts:

```javascript
const rows = JSON.parse(rawJson);          // the whole working set, in a variable

// Slice into batches and classify each batch with a subagent
const BATCH = 30;
const batches = [];
for (let i = 0; i < rows.length; i += BATCH) batches.push(rows.slice(i, i + BATCH));

const labeled = await Promise.all(
  batches.map((batch) =>
    task({
      description: `Classify these headlines:\n${JSON.stringify(batch.map((r) => r.headline))}`,
      subagentType: "classifier",
      responseSchema: labelsSchema,   // -> { labels: [{ index, category }] }
    })
  )
);

// Stitch labels back onto rows — in code, positionally, so nothing drifts
batches.forEach((batch, b) => {
  labeled[b].labels.forEach(({ index, category }) => { batch[index].category = category; });
});

// Aggregate deterministically — the model does zero counting
const counts = rows.reduce((acc, r) => (acc[r.category] = (acc[r.category] ?? 0) + 1, acc), {});
const sciTechForUser = rows.filter((r) => r.user === 72341 && r.category === "sci_tech").length;
const before = rows.filter((r) => r.date < "2004-08-01");
const sportsGtWorld =
  before.filter((r) => r.category === "sports").length >
  before.filter((r) => r.category === "world").length;

({ counts, sciTechForUser, sportsGtWorld });
```

## Why this beats a plain agent

- **The count is computed, not remembered.** `reduce` over an array is exact for
  240 rows or 240,000. There is no running total in the model's context to drift.
- **Only slices touch the model.** Each `classifier` sees ~30 headlines and
  returns ~30 labels. The full dataset never has to fit in one context window —
  the paper reports processing inputs up to two orders of magnitude beyond the
  model's context this way.
- **Filters compose in code.** "user 72341 AND sci_tech", "before Aug 2004 AND
  sports vs world" — these are one-line `filter`s once every row is labeled,
  instead of another lossy pass over the whole set.

## Recursive agents vs. the RLM paper

As the blog notes, this is closer to **recursive *agents*** than the paper's exact
RLM: the recursive calls are subagents with their own tools and state, and we
select slices to recurse on rather than loading the entire prompt into the
interpreter and recursing on it directly. But it's the same core bet — *let the
model write the loop that organizes its own context* — and it comes with a Deep
Agents perk: the orchestrator and the `classifier` subagents can run on
**different models** (say, a frontier orchestrator with cheap open-weight
classifiers) for cost/performance at scale.

## Try scaling it

Bump `N_HEADLINES` in the example up (and the batch size in your prompt). The
larger the input, the more the "count in code, classify in slices" approach pulls
ahead of a turn-by-turn agent that tries to keep the tally in its head.
