"""Example 4 — Generate and filter.

Produce several independent options, score them in code, keep the best. Multiple
`architect` subagents each propose a redesign of the same module; the
orchestrator scores them against the requirements and returns the winner with a
rationale.

Reach for this when exploring options beats a single one-shot answer
(architecture proposals, refactoring strategies, content variations).

Walkthrough: ../../walkthroughs/05-generate-and-filter.md
"""

from __future__ import annotations

from rlm_deep_agents.common import build_agent, print_header, run_workflow

SUBAGENTS = [
    {
        "name": "architect",
        "description": "Proposes a rate-limiter design with an explicit tradeoff analysis.",
        "system_prompt": (
            "You are a systems architect. Given the requirements, propose ONE "
            "concrete rate-limiter design. Return: a short design summary, the "
            "algorithm used, how it behaves under bursts, whether it supports "
            "multiple instances, and its main tradeoffs. Be specific and honest "
            "about weaknesses."
        ),
    }
]

REQUIREMENTS = """
Requirements for the rate limiter:
  - Limit each API key to 100 requests per minute.
  - Must behave correctly under bursty traffic.
  - Must work across multiple horizontally-scaled instances (shared state).
  - Keep operational complexity as low as possible.
""".strip()

PROMPT = f"""
Run a workflow to design a rate limiter by generating competing proposals and
keeping the best one.

Steps:
  1. Dispatch THREE `architect` subagents in parallel via task(), each asked for
     an independent design (e.g. nudge them toward token-bucket, sliding-window,
     and fixed-window approaches so the proposals differ).
  2. Score each proposal in code on: correctness under burst, multi-instance
     support, and operational simplicity (e.g. 0-3 each).
  3. Return the highest-scoring design, the score breakdown for all three, and a
     one-paragraph rationale for why the winner beat the others.

{REQUIREMENTS}
""".strip()


def main() -> None:
    print_header(
        "Generate and filter",
        """
        Generate several independent designs in parallel, score them against the
        requirements in code, and keep the best. Exploring options and filtering
        beats asking for one answer and hoping.
        """,
    )
    agent = build_agent(SUBAGENTS)
    run_workflow(agent, PROMPT)


if __name__ == "__main__":
    main()
