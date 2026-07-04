"""Example 3 — Adversarial verification.

A two-pass pattern that trades speed for confidence:

    Pass 1 (reviewer): cast a wide net for potential vulnerabilities.
    Pass 2 (verifier): hand each finding to an independent verifier that reads
                       the code fresh and returns CONFIRMED or REFUTED.

Only findings that survive verification make the final report. Reach for this
when false positives are costly (security audits, compliance checks).

Walkthrough: ../../walkthroughs/04-adversarial-verification.md
"""

from __future__ import annotations

from rlm_deep_agents.common import build_agent, print_header, run_workflow
from rlm_deep_agents.sample_data import SOURCE_TREE

SUBAGENTS = [
    {
        "name": "reviewer",
        "description": "Finds potential security vulnerabilities in code.",
        "system_prompt": (
            "You are a security auditor. Cast a wide net: report every potential "
            "vulnerability you can find, each with an id, file, line, and a short "
            "description. Prefer recall over precision here — the findings will be "
            "independently verified later."
        ),
    },
    {
        "name": "verifier",
        "description": "Independently verifies whether a reported vulnerability is real.",
        "system_prompt": (
            "You are a security verification specialist. Given a single reported "
            "vulnerability and the relevant code, independently decide whether it "
            "is genuinely exploitable. Be skeptical. Return CONFIRMED only for "
            "real, exploitable issues; otherwise return REFUTED with a reason."
        ),
    },
]

# Inline the code so both passes see identical source without needing PTC.
_CODE = "\n\n".join(f"// FILE: {path}\n{body}" for path, body in SOURCE_TREE.items())

PROMPT = f"""
Run a workflow to audit this codebase for security vulnerabilities, with an
independent verification pass so false positives don't reach the final report.

Steps:
  1. Pass 1: dispatch the `reviewer` subagent to find all potential
     vulnerabilities. Have it return a list of findings (id, file, line,
     description).
  2. Pass 2: for each finding, dispatch a `verifier` subagent in parallel that
     independently judges it CONFIRMED or REFUTED against the code below.
  3. Keep only CONFIRMED findings and return them as the final audit report,
     noting how many findings were refuted.

Code under review:
{_CODE}
""".strip()


def main() -> None:
    print_header(
        "Adversarial verification",
        """
        Find, then independently verify before keeping. Pass 1 casts a wide net;
        pass 2 sends each finding to a fresh verifier. Only findings that survive
        agreement make the report — false positives are filtered in code.
        """,
    )
    agent = build_agent(SUBAGENTS)
    run_workflow(agent, PROMPT)


if __name__ == "__main__":
    main()
