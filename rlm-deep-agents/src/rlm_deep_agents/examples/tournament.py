"""Example 5 — Tournament.

Head-to-head judging with winners advancing through elimination rounds. Several
`writer` subagents each produce a candidate rewrite; a `judge` subagent compares
them pairwise, round by round, until one champion remains.

Reach for this under subjective or *relative* criteria, where "which of these two
is better" is easier to answer than "score this one absolutely."

Walkthrough: ../../walkthroughs/06-tournament.md
"""

from __future__ import annotations

from rlm_deep_agents.common import build_agent, print_header, run_workflow

SUBAGENTS = [
    {
        "name": "writer",
        "description": "Rewrites a function for readability and clarity.",
        "system_prompt": (
            "You are an expert programmer focused on clean code. Rewrite the "
            "given function to maximize readability and clarity while preserving "
            "behavior. Return only the rewritten function plus a one-line note on "
            "your main improvement."
        ),
    },
    {
        "name": "judge",
        "description": "Compares two implementations and picks the more readable one.",
        "system_prompt": (
            "You are a code-quality judge. Compare implementation A and "
            "implementation B and pick the more readable, correct one. Return the "
            "winner as exactly 'A' or 'B' plus a one-sentence justification."
        ),
    },
]

MESSY_FUNCTION = '''
function createOrder(d) {
  var o = {};
  if (d && d.items && d.items.length > 0) {
    o.items = d.items; var t = 0;
    for (var i = 0; i < d.items.length; i++) { t = t + d.items[i].price * d.items[i].qty; }
    o.total = t; if (d.coupon) { if (d.coupon.type == "pct") { o.total = o.total - o.total * d.coupon.value; } else { o.total = o.total - d.coupon.value; } }
    o.status = "new"; return o;
  } else { return null; }
}
'''.strip()

PROMPT = f"""
Run a workflow to find the best readability rewrite of this function via a
single-elimination tournament.

Steps:
  1. Dispatch FOUR `writer` subagents in parallel, each producing an independent
     rewrite (nudge them toward different priorities, e.g. early returns, helper
     functions, immutability, naming).
  2. Run a bracket: pair the candidates and have the `judge` subagent pick the
     winner of each pair. Advance winners and repeat until one remains.
  3. Return the champion rewrite and the judge's reasoning at each round.

Function to rewrite:
{MESSY_FUNCTION}
""".strip()


def main() -> None:
    print_header(
        "Tournament",
        """
        Generate variants, then judge pairwise with winners advancing until one
        champion stands. The while-loop bracket is written in interpreter code;
        the judge subagent only ever answers 'A or B?'.
        """,
    )
    agent = build_agent(SUBAGENTS)
    run_workflow(agent, PROMPT)


if __name__ == "__main__":
    main()
