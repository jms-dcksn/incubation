"""Small, self-contained sample datasets used across the examples.

Nothing here is special — it just gives the workflows concrete, inline data to
orchestrate over so every example runs without external services or files.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Support tickets — for "classify and act".
# A mixed backlog: bugs, feature requests, and questions all in one list.
# ---------------------------------------------------------------------------
SUPPORT_TICKETS: list[dict[str, str]] = [
    {"id": "T-1", "text": "Login page returns a 500 error when the password contains a '#' character."},
    {"id": "T-2", "text": "Please add dark mode to the dashboard."},
    {"id": "T-3", "text": "How do I export my invoices as CSV?"},
    {"id": "T-4", "text": "The mobile app crashes on startup after the 4.2 update."},
    {"id": "T-5", "text": "Can you support SSO with Okta?"},
    {"id": "T-6", "text": "Where can I change my billing email address?"},
    {"id": "T-7", "text": "Webhook deliveries stopped arriving after 2am UTC last night."},
    {"id": "T-8", "text": "It would be great to schedule reports to be emailed weekly."},
]


# ---------------------------------------------------------------------------
# A tiny source tree — for "fan-out and synthesize" over files.
# Each value is the file's contents. A couple of files contain deliberate,
# obvious security issues for a reviewer subagent to find.
# ---------------------------------------------------------------------------
SOURCE_TREE: dict[str, str] = {
    "src/routes/login.js": (
        "export function login(req, res) {\n"
        "  const { user, pass } = req.body;\n"
        "  // BUG: string-concatenated SQL — injectable\n"
        "  const q = `SELECT * FROM users WHERE name = '${user}' AND pass = '${pass}'`;\n"
        "  return db.query(q);\n"
        "}\n"
    ),
    "src/routes/profile.js": (
        "export function profile(req, res) {\n"
        "  const id = req.params.id;\n"
        "  // OK: parameterized query\n"
        "  return db.query('SELECT * FROM users WHERE id = $1', [id]);\n"
        "}\n"
    ),
    "src/routes/admin.js": (
        "export function deleteUser(req, res) {\n"
        "  // BUG: no authentication / authorization check before a destructive action\n"
        "  return db.query('DELETE FROM users WHERE id = $1', [req.params.id]);\n"
        "}\n"
    ),
    "src/routes/health.js": (
        "export function health(req, res) {\n"
        "  return res.json({ ok: true });\n"
        "}\n"
    ),
}


# ---------------------------------------------------------------------------
# A long, "OOLONG-style" dataset — for the RLM long-context example.
# Thousands of headlines, each with a hidden category, a user id, and a date.
# The task is to *aggregate* across the whole set (count by category, filter by
# user/date), which is exactly the kind of work that drifts if the model tries
# to track a running total in its own context.
# ---------------------------------------------------------------------------
_CATEGORIES = ["world", "sports", "business", "sci_tech"]

_HEADLINE_TEMPLATES = {
    "world": [
        "Diplomats meet to discuss regional ceasefire",
        "Elections conclude amid record turnout",
        "Aid convoys reach flood-affected provinces",
        "Summit ends with joint climate declaration",
    ],
    "sports": [
        "Underdogs clinch title in overtime thriller",
        "Star striker signs record transfer deal",
        "Marathon record falls at city championship",
        "Home side advances to the semifinals",
    ],
    "business": [
        "Central bank holds interest rates steady",
        "Quarterly earnings beat analyst estimates",
        "Startup closes oversubscribed funding round",
        "Retail sales dip as consumers pull back",
    ],
    "sci_tech": [
        "Researchers unveil faster battery chemistry",
        "New telescope captures distant galaxy cluster",
        "Chipmaker announces next-generation processor",
        "Study links sleep patterns to memory recall",
    ],
}


def make_headlines(n: int = 240, seed: int = 7) -> list[dict[str, object]]:
    """Deterministically generate `n` headline rows.

    Each row: {"headline": str, "user": int, "date": "YYYY-MM-DD", "_category": str}

    The `_category` is included so you can compute the ground-truth answer in
    plain Python (see `expected_counts`) and check what the agent returns. In a
    real OOLONG task the category would be hidden and the agent would have to
    infer it — here we keep it so the example is verifiable offline.
    """
    import random

    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    for i in range(n):
        category = _CATEGORIES[i % len(_CATEGORIES)]
        headline = rng.choice(_HEADLINE_TEMPLATES[category])
        user = rng.choice([72341, 51002, 88190, 40771])
        year = rng.choice([2004, 2005])
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        rows.append(
            {
                "headline": headline,
                "user": user,
                "date": f"{year}-{month:02d}-{day:02d}",
                "_category": category,
            }
        )
    rng.shuffle(rows)
    return rows


def expected_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    """Ground-truth counts by category (for checking the agent's answer)."""
    counts = {c: 0 for c in _CATEGORIES}
    for r in rows:
        counts[str(r["_category"])] += 1
    return counts


def headlines_as_json(rows: list[dict[str, object]]) -> str:
    """Compact JSON with the hidden `_category` stripped out.

    This is the string we hand to the agent: it must classify + aggregate itself.
    """
    public = [
        {"headline": r["headline"], "user": r["user"], "date": r["date"]}
        for r in rows
    ]
    return json.dumps(public)
