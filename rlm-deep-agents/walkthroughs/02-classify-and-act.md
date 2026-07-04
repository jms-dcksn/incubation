# 02 — Classify and act

**Source:** [`examples/classify_and_act.py`](../src/rlm_deep_agents/examples/classify_and_act.py)
· **Run:** `uv run rlm-classify`

> Items are classified first, then each item is handled by a specialized subagent
> based on its classification. This lets you process mixed inputs where different
> items need different expertise.

**Reach for it when:** mixed inputs need different handling — triaging support
tickets, error logs, user feedback, any batch where the right handler depends on
the item's type.

## What we configure

Three specialists, one per category:

```python
SUBAGENTS = [
    {"name": "bug-fixer",       "description": "Investigates bug reports ...",       "system_prompt": "..."},
    {"name": "feature-analyst", "description": "Evaluates feature requests ...",     "system_prompt": "..."},
    {"name": "support-agent",   "description": "Answers user questions ...",         "system_prompt": "..."},
]
```

The input is a mixed backlog of support tickets from
[`sample_data.SUPPORT_TICKETS`](../src/rlm_deep_agents/sample_data.py) — bugs,
feature requests, and questions all interleaved.

## What we ask

```
1. Classify each ticket as exactly one of: "bug", "feature", or "question".
2. Route each ticket to the matching specialist via task() (in parallel).
3. Group the handled results by category and return one triage report.
```

## What the agent writes

The defining move is a **lookup table** from category to `subagentType`, so the
routing itself is deterministic code — the model's judgement is spent on
classification, not on remembering the routing rules:

```javascript
const SPECIALIST = {
  bug: "bug-fixer",
  feature: "feature-analyst",
  question: "support-agent",
};

// `tickets` already carries a `.category` the model assigned during classification
const handled = await Promise.all(
  tickets.map((ticket) =>
    task({
      description: `Handle this ${ticket.category}:\n${ticket.text}`,
      subagentType: SPECIALIST[ticket.category],
    })
  )
);
// ...group handled results by category into a single triage report
handled;
```

## Why this matters

- **Every item is routed.** The `map` covers the whole backlog; nothing is
  silently dropped because the model got bored halfway down the list.
- **Specialization without a monolith prompt.** Each subagent has its own focused
  system prompt. You're not cramming "if it's a bug do X, if it's a feature do
  Y..." into one giant instruction and hoping the model keeps them straight.
- **Classification and action are separated.** Classify once, then route with a
  plain dictionary. Adding a new category is: add a subagent + add one line to
  `SPECIALIST`.

## Variations

- **Two-phase classification.** For expensive classification, fan out a cheap
  `classifier` subagent first, collect labels, then route — see the
  [RLM long-context example](./08-rlm-long-context.md) for that shape at scale.
- **Fallback routing.** `SPECIALIST[ticket.category] ?? "general-purpose"` sends
  anything unclassified to the built-in general subagent.
