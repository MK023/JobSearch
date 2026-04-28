"""Tests for stack_match.score_match — pure function, no DB, no network."""

from src.worldwild.cv_skills import (
    CV_SKILLS_TIERED,
    MARCO_CV_SKILLS,
)
from src.worldwild.stack_match import score_match


class TestCvSkillsMirror:
    def test_three_tiers_present(self) -> None:
        assert set(CV_SKILLS_TIERED.keys()) == {"core", "strong", "familiar"}

    def test_union_matches_public_surface(self) -> None:
        union = CV_SKILLS_TIERED["core"] | CV_SKILLS_TIERED["strong"] | CV_SKILLS_TIERED["familiar"]
        assert union == MARCO_CV_SKILLS

    def test_tiers_are_disjoint(self) -> None:
        # No double-counting: a token can be in only one tier.
        c, s, f = (CV_SKILLS_TIERED[k] for k in ("core", "strong", "familiar"))
        assert c & s == frozenset()
        assert c & f == frozenset()
        assert s & f == frozenset()

    def test_core_includes_known_strong_signals(self) -> None:
        # Lock-in: these MUST stay in core. If someone removes them in a
        # CV update, we want a noisy test failure to force a discussion.
        for must_be_core in ("python", "kubernetes", "terraform", "aws", "fastapi"):
            assert must_be_core in CV_SKILLS_TIERED["core"]


class TestScoreMatchHappyPath:
    def test_full_match_scores_100(self) -> None:
        # Every extracted token is in Marco's CV.
        extracted = {"python", "fastapi", "kubernetes", "aws"}
        result = score_match(extracted)
        assert result.score == 100
        assert result.matched == frozenset(extracted)
        assert result.missing == frozenset()
        assert result.coverage_ratio == 1.0

    def test_partial_match_scores_proportionally(self) -> None:
        # 3 out of 4 in CV → 75%
        extracted = {"python", "kubernetes", "aws", "rabbitmq"}  # rabbitmq not in CV
        result = score_match(extracted)
        assert result.score == 75
        assert result.matched == frozenset({"python", "kubernetes", "aws"})
        assert result.missing == frozenset({"rabbitmq"})
        assert abs(result.coverage_ratio - 0.75) < 1e-9

    def test_zero_match_scores_zero(self) -> None:
        # Tech Marco doesn't have on the CV at all.
        extracted = {"cobol", "fortran", "vb6"}  # synthetic, never in MARCO_CV_SKILLS
        result = score_match(extracted)
        assert result.score == 0
        assert result.matched == frozenset()
        assert result.missing == frozenset(extracted)


class TestScoreMatchEdgeCases:
    def test_empty_extracted_returns_zero(self) -> None:
        result = score_match(set())
        assert result.score == 0
        assert result.matched == frozenset()
        assert result.missing == frozenset()
        assert result.coverage_ratio == 0.0

    def test_custom_cv_skills_isolates_logic(self) -> None:
        # Sanity: scoring must work against any reference set, not just
        # MARCO_CV_SKILLS. Useful for what-if scenarios + tests.
        extracted = {"foo", "bar", "baz"}
        cv_stub = frozenset({"foo", "qux"})
        result = score_match(extracted, cv_stub)
        assert result.score == 33  # 1/3 → 33.33 → rounds to 33
        assert result.matched == frozenset({"foo"})
        assert result.missing == frozenset({"bar", "baz"})

    def test_extracted_with_extra_unknown_terms_doesnt_inflate_score(self) -> None:
        # The denominator is |extracted|, so adding unknown tokens to the
        # offer LOWERS the score (Marco is missing them). This is the
        # right semantics: more unknown tech → bigger gap → lower fit.
        a = score_match({"python"})
        b = score_match({"python", "cobol"})
        assert a.score == 100
        assert b.score == 50

    def test_rounding_is_deterministic(self) -> None:
        # 2/3 = 66.66… → rounds to 67 (Python default banker's rounding
        # rounds half to even, but 66.66 is unambiguously > 66.5).
        result = score_match({"python", "kubernetes", "cobol"})
        assert result.score == 67


class TestStackMatchResultAccessors:
    def test_namedtuple_unpacks(self) -> None:
        # Down-stream callers may unpack instead of using attribute access.
        score, matched, missing, ratio = score_match({"python"})
        assert score == 100
        assert matched == frozenset({"python"})
        assert missing == frozenset()
        assert ratio == 1.0

    def test_attributes_are_immutable(self) -> None:
        result = score_match({"python", "rabbitmq"})
        # NamedTuple → no setattr. This guards downstream code from
        # accidentally mutating a "result" struct.
        try:
            result.score = 0  # type: ignore[misc]
        except AttributeError:
            pass
        else:
            raise AssertionError("StackMatchResult should be immutable")
