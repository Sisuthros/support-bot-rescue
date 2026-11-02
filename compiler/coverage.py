"""Deterministic policy-coverage accounting. No model, no network.

Splits a policy into sentences and labels each one by whether compiled
code enforces it (a rule quotes it), a human must review it (the compiler
listed it as uncovered), or the compiler said nothing about it at all.
"""
from __future__ import annotations

import re
from typing import Any

_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")


def split_sentences(policy_text: str) -> list[str]:
    """Split policy text into sentences.

    Markdown headings and empty lines are skipped; bullet lines count
    (their bullet marker is stripped). Each remaining line is split on
    sentence-ending punctuation.
    """
    sentences: list[str] = []
    text = (policy_text or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#") or line in {"---", "***", "___"}:
            continue
        line = _BULLET_RE.sub("", line)
        for match in _SENTENCE_RE.finditer(line):
            sentence = match.group(0).strip()
            if sentence and any(ch.isalnum() for ch in sentence):
                sentences.append(sentence)
    return sentences


def _quote_of(item: Any) -> str | None:
    if isinstance(item, dict):
        q = item.get("quote")
    else:
        q = getattr(item, "quote", None)
    return q if isinstance(q, str) and q else None


def _spec_parts(spec: Any) -> tuple[dict[str, str | None], dict[str, str]]:
    """Return ({rule quote: rule id or None}, {uncovered quote: reason})."""
    if spec is None:
        return {}, {}
    if isinstance(spec, dict):
        rules = spec.get("rules") or []
        uncovered = spec.get("uncovered") or []
    else:
        rules = getattr(spec, "rules", ()) or ()
        uncovered = getattr(spec, "uncovered", ()) or ()
    enforced: dict[str, str | None] = {}
    for rule in rules:
        q = _quote_of(rule)
        if q:
            rid = rule.get("id") if isinstance(rule, dict) else getattr(rule, "id", None)
            enforced[q] = rid if isinstance(rid, str) else None
    review: dict[str, str] = {}
    for item in uncovered:
        q = _quote_of(item)
        if not q:
            continue
        reason = item.get("reason") if isinstance(item, dict) else getattr(item, "reason", "")
        review[q] = reason if isinstance(reason, str) else ""
    return enforced, review


def compute_coverage(policy_text: str, spec: Any = None) -> dict[str, Any]:
    """Label every policy sentence and build the coverage headline."""
    enforced, review = _spec_parts(spec)
    entries: list[dict[str, Any]] = []
    counts = {"enforced": 0, "needs_review": 0, "not_addressed": 0}
    for sentence in split_sentences(policy_text):
        if sentence in enforced:
            label, reason, rule_id = "enforced", None, enforced[sentence]
        elif sentence in review:
            label, reason, rule_id = "needs_review", review[sentence], None
        else:
            label, reason, rule_id = "not_addressed", None, None
        counts[label] += 1
        entries.append({"sentence": sentence, "quote": sentence, "label": label,
                        "status": label, "reason": reason, "rule_id": rule_id})
    total = len(entries)
    headline = (f"{counts['enforced']} of {total} policy sentences are enforced by code; "
                f"{counts['needs_review']} need human review; "
                f"{counts['not_addressed']} were not addressed by the compiler")
    return {"headline": headline, "sentences": entries, "total": total,
            "counts": dict(counts),
            "enforced_count": counts["enforced"],
            "needs_review_count": counts["needs_review"],
            "not_addressed_count": counts["not_addressed"]}


# Convenience aliases.
coverage = compute_coverage
policy_coverage = compute_coverage
