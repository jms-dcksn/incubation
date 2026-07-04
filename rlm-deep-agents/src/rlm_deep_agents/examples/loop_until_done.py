"""Example 6 — Loop until done.

Repeat passes until one turns up nothing new. The agent runs a discovery pass,
deduplicates against everything it has already found, and only starts another
pass if the previous one surfaced something fresh. It stops when a pass adds
nothing.

Reach for this when the scope is unknown up front and you want completeness
rather than a fixed number of results (exhaustive search, dead-code detection,
dependency audits).

Walkthrough: ../../walkthroughs/07-loop-until-done.md
"""

from __future__ import annotations

from rlm_deep_agents.common import build_agent, print_header, run_workflow

SUBAGENTS = [
    {
        "name": "analyzer",
        "description": "Finds unused exports, unreachable functions, and dead code paths.",
        "system_prompt": (
            "You are a code analyst specializing in dead-code detection. Given "
            "the code and a list of what has already been found, find ADDITIONAL "
            "dead code only (unused exports, unreachable functions, orphaned "
            "modules). Report each with a stable id, file path, and evidence. If "
            "there is nothing new, return an empty list."
        ),
    }
]

# A small module with layered dead code: some obvious, some only reachable-looking
# until you notice its one caller is itself unused. A single pass tends to miss
# the second layer; the loop keeps going until a pass finds nothing.
_CODE = '''
// FILE: utils.js
export function used() { return format(1); }        // used by app.js
export function format(n) { return String(n); }      // used by used()
export function legacyFormat(n) { return n + ""; }   // dead: only caller is legacyExport
export function legacyExport() { return legacyFormat(2); } // dead: never imported anywhere
export function orphan() { return 42; }              // dead: never imported anywhere

// FILE: app.js
import { used } from "./utils.js";
console.log(used());
'''.strip()

PROMPT = f"""
Run a workflow to exhaustively find all dead code in this project.

Steps:
  1. Repeatedly dispatch the `analyzer` subagent. Each round, pass it the set of
     ids already found so it only reports NEW dead code.
  2. Deduplicate results against what you've already collected (by id).
  3. Stop when a round returns nothing new (convergence).
  4. Return the consolidated list of dead code and how many passes it took.

Code to analyze:
{_CODE}
""".strip()


def main() -> None:
    print_header(
        "Loop until done",
        """
        A discovery loop that keeps dispatching passes, deduping against what it
        has found, until a pass surfaces nothing new. Scope is discovered, not
        assumed — the convergence check lives in interpreter code.
        """,
    )
    agent = build_agent(SUBAGENTS)
    run_workflow(agent, PROMPT)


if __name__ == "__main__":
    main()
