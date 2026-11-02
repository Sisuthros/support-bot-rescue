"""Deterministic policy-coverage accounting. No model, no network.

Splits a policy into sentences and labels each one by whether compiled
code enforces it (a rule quotes it), a human must review it (the compiler
listed it as uncovered), the compiler says it states no obligation
(informational), or the compiler said nothing about it at all
(unaccounted -- the silent case, never hidden).
"""
from __future__ import annotations

import re
from typing import Any

_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_ABBREV_RE = re.compile(r"([A-Za-z]+(?:\.[A-Za-z]+)*)$")
_ABBREVIATIONS = {"e.g", "i.e", "etc", "vs", "mr", "mrs", "ms", "dr", "no", "approx"}


def _is_protected_period(line: str, i: int) -> bool:
    # A period with no following space sits inside a decimal (49.99), an
    # abbreviation (e.g.), a URL or an email address: never a boundary.
    if i + 1 < len(line) and not line[i + 1].isspace():
        return True
    if i > 0 and i + 1 < len(line) and line[i - 1].isdigit() and line[i + 1].isdigit():
        return True
    m = _ABBREV_RE.search(line[:i])
    return bool(m and m.group(1).lower() in _ABBREVIATIONS)


def split_sentences(policy_text: str) -> list[str]:
    """Split policy text into sentences.

    Markdown headings and empty lines are skipped; bullet lines count
    (their bullet marker is stripped). A period between digits, after a
    common abbreviation, or inside a URL/email does not split.
    """
    sentences: list[str] = []
    text = (policy_text or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#") or line in {"---", "***", "___"}:
            continue
        line = _BULLET_RE.sub("", line)
        start = 0
        for i, ch in enumerate(line):
            if ch not in ".!?":
                continue
            if ch == "." and _is_protected_period(line, i):
                continue
            sentence = line[start:i + 1].strip()
            if sentence and any(c.isalnum() for c in sentence):
                sentences.append(sentence)
            start = i + 1
        tail = line[start:].strip()
        if tail and any(c.isalnum() for c in tail):
            sentences.append(tail)
    return sentences


def _norm(text: str) -> str:
    return " ".join(str(text).split()).strip().rstrip(".!?")


def _matches(sentence_norm: str, quote_norm: str) -> bool:
    return bool(quote_norm) and (quote_norm in sentence_norm or sentence_norm in quote_norm)


def _quote_of(item: Any) -> str | None:
    if isinstance(item, dict):
        q = item.get("quote")
    else:
        q = getattr(item, "quote", None)
    return q if isinstance(q, str) and q else None


def _spec_parts(spec: Any) -> tuple[dict[str, str | None], dict[str, str], list[str]]:
    """Return ({rule quote: rule id or None}, {uncovered quote: reason}, [informational])."""
    if spec is None:
        return {}, {}, []
    if isinstance(spec, dict):
        rules = spec.get("rules") or []
        uncovered = spec.get("uncovered") or []
        informational = spec.get("informational") or []
    else:
        rules = getattr(spec, "rules", ()) or ()
        uncovered = getattr(spec, "uncovered", ()) or ()
        informational = getattr(spec, "informational", ()) or ()
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
    info: list[str] = []
    for item in informational:
        q = item if isinstance(item, str) else _quote_of(item)
        if q:
            info.append(q)
    return enforced, review, info


def compute_coverage(policy_text: str, spec: Any = None) -> dict[str, Any]:
    """Label every policy sentence and build the coverage headline."""
    enforced, review, informational = _spec_parts(spec)
    enforced_n = [(_norm(q), rid) for q, rid in enforced.items()]
    review_n = [(_norm(q), r) for q, r in review.items()]
    info_n = [_norm(q) for q in informational]
    entries: list[dict[str, Any]] = []
    counts = {"enforced": 0, "needs_review": 0, "informational": 0, "unaccounted": 0}
    for sentence in split_sentences(policy_text):
        sn = _norm(sentence)
        label, reason, rule_id = "unaccounted", None, None
        for qn, rid in enforced_n:
            if _matches(sn, qn):
                label, rule_id = "enforced", rid
                break
        if label == "unaccounted":
            for qn, r in review_n:
                if _matches(sn, qn):
                    label, reason = "needs_review", r
                    break
        if label == "unaccounted" and any(_matches(sn, qn) for qn in info_n):
            label = "informational"
        counts[label] += 1
        entries.append({"sentence": sentence, "label": label,
                        "reason": reason, "rule_id": rule_id})
    obligations = counts["enforced"] + counts["needs_review"] + counts["unaccounted"]
    headline = (f"{counts['enforced']} of {obligations} obligations are enforced by code; "
                f"{counts['needs_review']} need human review; "
                f"{counts['informational']} informational sentences, {counts['unaccounted']} unaccounted")
    return {"headline": headline, "sentences": entries, "total": len(entries),
            "counts": dict(counts)}
