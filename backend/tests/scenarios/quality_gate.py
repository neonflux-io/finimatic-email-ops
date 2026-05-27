from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


BANNED_PHRASES = [
    "i hope this finds you well",
    "leverage",
    "synergy",
    "cutting-edge",
    "innovative solution",
    "reach out",
    "circle back",
    "touch base",
    "paradigm",
    "i wanted to follow up",
    "just checking in",
]

BANNED_OPENERS = [
    "i hope",
    "thank you for",
    "thanks for your reply",
    "great to hear",
    "i appreciate your response",
]

FABRICATION_PATTERNS = [
    r"\b\d+%\b",
    r"\b\$ ?\d+(?:,\d{3})*(?:\.\d+)?\b",
    r"\bINR ?\d+(?:,\d{3})*\b",
    r"\b(?:24|48|72)\s*hours?\b",
    r"https?://",
    r"\[[^\]]+\]",
]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def evaluate(subject: str, body: str, *, technical: bool = False) -> list[str]:
    errors: list[str] = []
    normalized = " ".join(body.lower().split())
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    first_line_lower = first_line.lower()

    if subject and not subject.lower().startswith("re:"):
        errors.append("subject_not_reply")

    for opener in BANNED_OPENERS:
        if first_line_lower.startswith(opener):
            errors.append(f"banned_opener:{opener}")

    for phrase in BANNED_PHRASES:
        if phrase in normalized:
            errors.append(f"banned_phrase:{phrase}")

    for pattern in FABRICATION_PATTERNS:
        if re.search(pattern, body, flags=re.IGNORECASE):
            errors.append(f"fabrication_pattern:{pattern}")

    if not technical and _word_count(body) > 200:
        errors.append("too_long")

    if "ross dmello" not in normalized:
        errors.append("missing_ross_dmello_signature")

    if "ai systems engineer" not in normalized:
        errors.append("missing_role_signature")

    cta_markers = [
        "would you be open",
        "could you share",
        "please share",
        "are you available",
        "does that sound",
        "would it make sense",
        "can we",
        "shall we",
    ]
    cta_count = sum(normalized.count(marker) for marker in cta_markers)
    if cta_count != 1:
        errors.append(f"cta_count:{cta_count}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic reply quality gate.")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--technical", action="store_true")
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    errors = evaluate(args.subject, body, technical=args.technical)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
