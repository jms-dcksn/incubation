"""Example 1 — Classify and act.

Route each item to a specialist by type. The agent classifies every ticket, then
dispatches it to the subagent that handles that category:

    bug      -> bug-fixer
    feature  -> feature-analyst
    question -> support-agent

Reach for this when mixed inputs need different handling. Coverage is structural:
every ticket is routed, none are silently dropped.

Walkthrough: ../../walkthroughs/02-classify-and-act.md
"""

from __future__ import annotations

from rlm_deep_agents.common import build_agent, print_header, run_workflow
from rlm_deep_agents.sample_data import SUPPORT_TICKETS

SUBAGENTS = [
    {
        "name": "bug-fixer",
        "description": "Investigates bug reports and provides reproduction steps.",
        "system_prompt": (
            "You are a bug triage specialist. Investigate the bug report and "
            "provide clear, numbered reproduction steps and a likely root cause."
        ),
    },
    {
        "name": "feature-analyst",
        "description": "Evaluates feature requests for feasibility and effort.",
        "system_prompt": (
            "You are a product analyst. Evaluate the feature request for "
            "technical feasibility, rough effort (S/M/L), and potential impact."
        ),
    },
    {
        "name": "support-agent",
        "description": "Answers user questions based on product knowledge.",
        "system_prompt": (
            "You are a support specialist. Answer the user's question clearly "
            "and concisely, with concrete steps where relevant."
        ),
    },
]

PROMPT = f"""
Run a workflow to triage this support backlog.

Steps:
  1. Classify each ticket as exactly one of: "bug", "feature", or "question".
  2. Route each ticket to the matching specialist subagent via task():
     bug -> bug-fixer, feature -> feature-analyst, question -> support-agent.
     Dispatch them in parallel.
  3. Group the handled results by category and return one triage report.

Tickets (JSON):
{SUPPORT_TICKETS}
""".strip()


def main() -> None:
    print_header(
        "Classify and act",
        """
        Mixed inputs, different handling. The agent classifies every ticket and
        routes it to a specialist subagent. A dictionary maps category ->
        subagentType, so the routing itself is deterministic code.
        """,
    )
    agent = build_agent(SUBAGENTS)
    run_workflow(agent, PROMPT)


if __name__ == "__main__":
    main()
