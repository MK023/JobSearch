"""Stack-match scoring: how well does an offer's tech stack overlap Marco's CV?

Pure-function module. Input is the canonical token set produced by
``stack_extract.extract_stack``; output is a ``StackMatchResult`` with
score (0-100), the matched / missing breakdown, and the raw coverage
ratio (useful for downstream weighting beyond a single % value).

Scoring is intentionally simple in PR #2:

    score = round( |extracted ∩ cv_skills| / |extracted| × 100 )

We don't (yet) weight by tier (core / strong / familiar) — the Tier
breakdown is exposed by ``cv_skills.CV_SKILLS_TIERED`` for a future
weighted variant if ``decisions`` data shows simple % is too noisy.

Edge cases:
- empty extracted set → score 0, both sides empty
- offer fully outside Marco's stack → score 0, missing == extracted
- offer fully inside Marco's stack → score 100

The "missing" set is the most useful field for downstream UX: it tells
Marco at-a-glance which skills the role asks for that he doesn't yet
have on the CV — direct input for the ramp-up roadmap.
"""

from __future__ import annotations

from typing import NamedTuple

from .cv_skills import MARCO_CV_SKILLS


class StackMatchResult(NamedTuple):
    """Outcome of comparing an offer's stack against a CV reference set."""

    score: int  # rounded 0-100
    matched: frozenset[str]  # tokens in BOTH offer and CV
    missing: frozenset[str]  # tokens in offer but NOT in CV
    coverage_ratio: float  # raw |matched|/|extracted|, 0.0..1.0


_EMPTY = StackMatchResult(
    score=0,
    matched=frozenset(),
    missing=frozenset(),
    coverage_ratio=0.0,
)


def score_match(
    extracted: set[str],
    cv_skills: frozenset[str] = MARCO_CV_SKILLS,
) -> StackMatchResult:
    """Compare an extracted offer stack against a CV skill set.

    The default ``cv_skills`` is Marco's canonical mirror. Tests can pass a
    custom frozenset to verify scoring logic in isolation.
    """
    if not extracted:
        return _EMPTY
    matched = frozenset(extracted & cv_skills)
    missing = frozenset(extracted - cv_skills)
    coverage_ratio = len(matched) / len(extracted)
    return StackMatchResult(
        score=round(coverage_ratio * 100),
        matched=matched,
        missing=missing,
        coverage_ratio=coverage_ratio,
    )
