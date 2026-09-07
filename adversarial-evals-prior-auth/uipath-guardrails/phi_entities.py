"""Custom PHI entity patterns for a prior authorization intake agent."""

import re
from typing import Any, Iterator

PHI_PATTERNS: dict[str, re.Pattern[str]] = {
    "MRN": re.compile(r"\bMRN[\s:#-]*([A-Z]{0,3}\d{6,10})\b", re.I),
    "MEMBER_ID": re.compile(r"\b([A-Z]{3}\d{9})\b"),
    "NPI": re.compile(r"\bNPI[\s:#-]*(\d{10})\b", re.I),
    "ICD10": re.compile(
        r"\b(?:ICD-?10|dx|diagnosis)[\s:#-]*([A-TV-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?)\b", re.I),
    "CPT": re.compile(r"\b(?:CPT|procedure)[\s:#-]*(\d{5})\b", re.I),
    "HCPCS": re.compile(r"\b(?:HCPCS)[\s:#-]*([A-V]\d{4})\b", re.I),
    "AUTH_CASE": re.compile(r"\b(?:auth|case)[\s:#-]*(PA-?\d{6,10})\b", re.I),
    "DOB": re.compile(r"\b(?:DOB|date of birth)[\s:#-]*(\d{1,2}/\d{1,2}/\d{4})\b", re.I),
}


def _walk(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def find_phi(payload: Any) -> set[str]:
    """Return the labels of every PHI entity found anywhere in the payload."""
    hits: set[str] = set()
    for text in _walk(payload):
        for label, pattern in PHI_PATTERNS.items():
            if pattern.search(text):
                hits.add(label)
    return hits


def contains_phi(payload: dict[str, Any]) -> bool:
    """Single rule passed to the middleware. Never raises."""
    return bool(find_phi(payload))
