"""Example 7 — RLM long-context aggregation (OOLONG-style).

This is the flagship of the "How to Use RLMs in Deep Agents" blog. The task is a
data-aggregation problem over a large set of rows where the answer depends on
examining (nearly) *every* row:

    thousands of headlines, each with a user and date but NO visible category.
    Questions like "how many world headlines are there?" or "for user 72341, how
    many sci/tech headlines?" require classifying every row and aggregating.

Turn-by-turn, a model has to track running totals in its own context, and those
totals drift as the count grows (context rot). The RLM approach keeps the data
and the counting **in interpreter variables and code**, and only uses subagents
for the judgement-heavy part (classifying a slice of headlines). The final
counts are computed deterministically in JavaScript, never in the model's head.

Shape of the workflow the agent should write:
  1. Load the headlines JSON into an interpreter variable (the "working set").
  2. Slice it into batches.
  3. Dispatch a `classifier` subagent per batch via task() to label each row.
  4. Reduce the labels into counts in code (group-by, filter-by-user, etc.).
  5. Answer the questions from those code-computed aggregates.

We also print the ground-truth counts (computed in plain Python) so you can check
the agent's answer.

Walkthrough: ../../walkthroughs/08-rlm-long-context.md
"""

from __future__ import annotations

from rlm_deep_agents.common import build_agent, print_header, run_workflow
from rlm_deep_agents.sample_data import (
    expected_counts,
    headlines_as_json,
    make_headlines,
)

# Keep it modest by default so it runs quickly and cheaply. Bump `n` up (and
# batch harder) to feel the RLM advantage on genuinely long inputs.
N_HEADLINES = 240

SUBAGENTS = [
    {
        "name": "classifier",
        "description": (
            "Classifies a batch of news headlines into one of four topics: "
            "world, sports, business, sci_tech."
        ),
        "system_prompt": (
            "You are a news classifier. For EACH headline in the batch, assign "
            "exactly one category from: world, sports, business, sci_tech. "
            "Return an array aligned to the input order: for each item its index "
            "and its category. Do not skip any item; do not add commentary."
        ),
    }
]


def build_prompt(headlines_json: str) -> str:
    return f"""
Run a workflow to answer aggregation questions over this headline dataset. The
category of each headline is NOT given — you must classify to find it.

IMPORTANT: keep the dataset and all counting in interpreter variables and code.
Do not try to hold running totals in your own reasoning — classify in batches
with subagents, then aggregate deterministically in JavaScript.

Steps:
  1. Parse the JSON array into an interpreter variable `rows`.
  2. Split `rows` into batches (e.g. 30 per batch).
  3. For each batch, dispatch a `classifier` subagent via task() that returns a
     category for every headline in the batch. Run batches in parallel.
  4. Merge the labels back onto the rows in code.
  5. Compute, entirely in code, and report:
       a) total count per category (world / sports / business / sci_tech),
       b) for user 72341: how many sci_tech headlines,
       c) whether "sports" headlines outnumber "world" headlines before Aug 2004
          (date < "2004-08-01").
  6. Return the four category totals and the answers to (b) and (c).

Headlines (JSON array of {{headline, user, date}}):
{headlines_json}
""".strip()


def main() -> None:
    print_header(
        "RLM long-context aggregation",
        """
        Classify every row with subagents, but keep the data and the counting in
        interpreter code — not in the model's context — so totals don't drift.
        This is the Recursive Language Model idea applied to a long-context
        aggregation task.
        """,
    )

    rows = make_headlines(N_HEADLINES)
    truth = expected_counts(rows)
    print(f"\n(ground-truth category counts for {N_HEADLINES} rows: {truth})")
    print("The agent must recover counts close to these by classifying + counting in code.\n")

    agent = build_agent(SUBAGENTS)
    run_workflow(agent, build_prompt(headlines_as_json(rows)))


if __name__ == "__main__":
    main()
