"""Example 2 — Fan-out and synthesize (with programmatic tool calling).

The same work across many items in parallel, then combined into one report.

This example also shows **programmatic tool calling (PTC)**: the workflow first
*discovers* the files to review by calling a tool from interpreter code
(`tools.glob(...)`), then fans out one `reviewer` subagent per file, then merges
every finding into a single prioritized report.

Discovering files from interpreter code requires PTC, so we enable `glob` (and
`read_file`) in the allowlist. We seed a small virtual filesystem so there is
something to discover.

Walkthrough: ../../walkthroughs/03-fanout-and-synthesize.md
"""

from __future__ import annotations

from rlm_deep_agents.common import build_agent, print_header, run_workflow
from rlm_deep_agents.sample_data import SOURCE_TREE

SUBAGENTS = [
    {
        "name": "reviewer",
        "description": "Reviews one file for security issues, citing lines and severity.",
        "system_prompt": (
            "You are a security-focused code reviewer. Read the file carefully "
            "and report any injection, authentication, or authorization issues. "
            "For each issue give the line number, a severity of high/medium/low, "
            "and a one-line description. If the file is clean, say so."
        ),
    }
]

PROMPT = """
Run a workflow that security-reviews every route file in this project.

Steps:

Use file tools to find the route files (glob **/*.js from /).
Dispatch one reviewer subagent per file, in parallel, via tools.task() from inside eval. Ask each to return structured findings (file, line, severity, description).
Merge all findings, sort by severity (high first), drop duplicates, and return a single prioritized report of the top risks.
Tool Usage Rules
You have access to filesystem tools and a code interpreter (eval).

Critical: You must NEVER call any tools directly as top-level tool calls. ALL tool calls — including glob, read_file, ls, and task — must happen inside eval() code blocks, using the tools.* prefix.

Critical: The eval sandbox is stateful and shared across all eval calls in a single run. To avoid variable redeclaration errors, always wrap eval code in an async IIFE:

// ✅ CORRECT — tools.* prefix, async IIFE wrapper, task() inside eval
await eval({
  code: `
    (async () => {
      const files = await tools.glob({ pattern: '**/*.js', path: '/' });
      const routeFiles = files.filter(f => f.includes('/routes/'));
      const results = await Promise.all(routeFiles.map(file =>
        tools.task({
          subagentType: 'reviewer',
          label: 'review ' + file.split('/').pop(),
          description: \`Security-review \${file}. Return { findings: [{ file, line, severity, description }] }\`
        })
      ));
      return results;
    })();
  `
});

// ❌ WRONG — direct top-level tool calls, bare task()/glob(), const without IIFE
glob({ pattern: '**/*.js' });
task({ subagentType: 'reviewer', ... });
const files = await tools.glob(...); // outside an IIFE — will cause redeclaration errors
The only tools you may call directly (outside eval) are: write_todos() and eval() itself.
""".strip()


def main() -> None:
    print_header(
        "Fan-out and synthesize",
        """
        Discover files with a tool call from code (PTC / tools.glob), fan out one
        reviewer subagent per file in parallel, then merge into one prioritized
        report. Every file is covered because the loop, not the model, decides
        the set.
        """,
    )
    # PTC allowlist exposes the filesystem tools inside the interpreter as
    # tools.glob(...) / tools.readFile(...). Files are seeded into the Deep
    # Agents virtual filesystem so glob has something to find.
    agent = build_agent(SUBAGENTS, ptc=["glob", "read_file", "ls", "write_file", "edit_file", "grep"])
    run_workflow(agent, PROMPT, files=SOURCE_TREE)


if __name__ == "__main__":
    main()
