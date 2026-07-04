"""Example 0 — Quickstart: the canonical fan-out.

The smallest possible dynamic-subagent program: one subagent per page of a
document, dispatched in parallel from a single JavaScript loop rather than 300
separate tool calls. This is the exact example the blogs open with:

    const results = await Promise.all(pages.map(page =>
      task({ description: `Summarize page ${page.number}`, subagentType: "summarizer" })
    ));

We define a single `summarizer` subagent, hand the agent a handful of "pages"
inline, and ask for a "workflow" — the trigger word that tells the interpreter
to orchestrate with `task()` from code.

Walkthrough: ../../walkthroughs/01-quickstart-fanout.md
"""

from __future__ import annotations

from rlm_deep_agents.common import build_agent, print_header, run_workflow

SUBAGENTS = [
    {
        "name": "summarizer",
        "description": "Summarizes a single page of text into one tight sentence.",
        "system_prompt": (
            "You are a summarizer. Given the text of one page, return a single "
            "clear sentence capturing its main point. No preamble."
        ),
    }
]

# Stand-ins for pages of a long document. In a real RLM workflow this could be
# hundreds of pages; the orchestration code is identical either way.
PAGES = [
    "Chapter 1 introduces the water cycle: evaporation lifts water into the air.",
    "Chapter 2 covers condensation, where vapor cools and forms clouds.",
    "Chapter 3 explains precipitation as rain, snow, sleet, and hail.",
    "Chapter 4 describes collection in oceans, lakes, rivers, and groundwater.",
    "Chapter 5 ties the stages together into one continuous, sun-driven loop.",
]

PROMPT = f"""
Run a workflow that summarizes every page below, one summarizer subagent per
page dispatched in parallel with task(), then combine the sentences into a
single ordered summary of the whole document.

Pages (JSON array, index = page number):
{PAGES}
""".strip()


def main() -> None:
    print_header(
        "Quickstart: fan-out with dynamic subagents",
        """
        One `summarizer` subagent per page, dispatched in parallel from a single
        Promise.all in interpreter code. Coverage is structural: every page gets
        a subagent, not a model judgement call about which pages to sample.
        """,
    )
    agent = build_agent(SUBAGENTS)
    run_workflow(agent, PROMPT)


if __name__ == "__main__":
    main()
