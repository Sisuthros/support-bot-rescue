"""Deterministic check for free-text policy claims in a reply.

This check only compares words. It uses lexical overlap between a claim
and the policy sentences, so a paraphrase can slip past it or be flagged
wrongly. A flag is therefore a prompt for human review. It is never a
rule violation and it never changes a rule verdict.
"""
from __future__ import annotations

import re

# 0.5 sits between the grounded citation in the tests (about 0.6 of its
# content words appear in one policy sentence) and the invented claims
# (about 0.4 or less), so grounded wording passes and invented wording flags.
GROUNDING_THRESHOLD = 0.5

_CLAIM_RE = re.compile(
    r"\b(?:our|the)\s+(?:\w+\s+)?(?:policies|policy|guidelines|rules|terms)\s+"
    r"(?:says|say|allows|allow|requires|require|states|state|permits|permit|lets|let)\b"
    r"|\b(?:under|per)\s+(?:our|the)\s+(?:\w+\s+)?"
    r"(?:policies|policy|guidelines|rules|terms)\b",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ORDER_ID_RE = re.compile(r"\b[a-z]-\d+\b", re.IGNORECASE)

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "because", "been",
        "but", "by", "cannot", "for", "from", "has", "have", "i", "in",
        "into", "is", "it", "its", "of", "on", "or", "so", "that",
        "this", "to", "was", "were", "will", "with", "you", "your",
    }
)
_NON_CONTENT = frozenset(
    {
        "policy", "policies", "guidelines", "rules", "terms", "per",
        "under", "our", "the", "says", "allows",
    }
)


def _split_sentences(text: str) -> list[str]:
    """Split text into trimmed sentences."""
    return [part.strip() for part in _SENTENCE_RE.findall(text) if part.strip()]


def _tokens(text: str) -> list[str]:
    """Return lowercase alphanumeric tokens, with order ids removed."""
    without_order_ids = _ORDER_ID_RE.sub(" ", text.lower())
    return _TOKEN_RE.findall(without_order_ids)


def _content_words(sentence: str) -> set[str]:
    """Return the content words of a sentence."""
    return {
        token
        for token in _tokens(sentence)
        if token not in _STOPWORDS and token not in _NON_CONTENT
    }


def find_policy_claims(reply: str) -> list[str]:
    """Return the sentences in a reply that assert policy."""
    return [s for s in _split_sentences(reply) if _CLAIM_RE.search(s)]


def check_reply(reply: str, policy_text: str) -> list[dict]:
    """Flag policy claims that no policy sentence grounds.

    Each flag is a dict with the claim, the closest policy sentence and
    the share of claim content words found in that sentence.
    """
    policy_sentences = _split_sentences(policy_text)
    policy_word_sets = [set(_tokens(sentence)) for sentence in policy_sentences]
    flags: list[dict] = []
    for claim in find_policy_claims(reply):
        content_words = _content_words(claim)
        if not content_words:
            continue
        best_sentence = ""
        best_overlap = 0.0
        for sentence, words in zip(policy_sentences, policy_word_sets):
            overlap = len(content_words & words) / len(content_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_sentence = sentence
        if best_overlap < GROUNDING_THRESHOLD:
            flags.append(
                {
                    "flag": "ungrounded_policy_claim",
                    "claim": claim,
                    "best_policy_sentence": best_sentence,
                    "overlap": round(best_overlap, 2),
                }
            )
    return flags
