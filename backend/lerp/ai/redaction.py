"""Local redaction of identifiers before any text leaves for a hosted model.

Deliberately simple for now; a small local NER model joins these rules in Phase 3.
"""

import re

_MYKAD = re.compile(r"\b\d{6}-?\d{2}-?\d{4}\b")  # Malaysian IC: YYMMDD-PB-###G
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")


def redact(text: str) -> str:
    text = _MYKAD.sub("[IC]", text)
    return _EMAIL.sub("[EMAIL]", text)
