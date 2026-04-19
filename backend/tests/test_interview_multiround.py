"""Tests for multi-round interview support introduced in migration 013.

Covers:
- The 1:1 unique constraint is dropped — multiple rounds per analysis allowed.
- ``round_number`` ordering and defaults.
- ``outcome`` persistence and validation.
- Back-compat: ``analysis.interview`` (singular) still resolves to the
  latest round; ``create_or_update_interview`` updates the latest round
  in place; ``get_interview_by_analysis`` returns the latest.
- New helpers: ``create_next_round`` increments round_number; ``set_outcome``
  validates and persists.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.analysis.models import AnalysisStatus
from src.interview.models import Interview, InterviewOutcome
from src.interview.service import (
    InterviewScheduleData,
    create_next_round,
    create_or_update_interview,
    get_interview_by_analysis,
    get_interview_rounds,
    set_outcome,
)


def _at(hours_from_now: int = 24) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours_from_now)


class TestMultipleRoundsPerAnalysis:
    def test_two_rounds_can_coexist(self, db_session, test_analysis):
        r1 = Interview(analysis_id=test_analysis.id, round_number=1, scheduled_at=_at(24))
        r2 = Interview(analysis_id=test_analysis.id, round_number=2, scheduled_at=_at(72))
        db_session.add_all([r1, r2])
        db_session.commit()

        rounds = get_interview_rounds(db_session, test_analysis.id)
        assert [r.round_number for r in rounds] == [1, 2]

    def test_default_round_number_is_one(self, db_session, test_analysis):
        i = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=_at(24), interview_type="conoscitivo"),
        )
        assert i is not None
        assert i.round_number == 1


class TestBackCompatLatestRound:
    def test_create_or_update_targets_latest_round(self, db_session, test_analysis):
        r1 = Interview(analysis_id=test_analysis.id, round_number=1, scheduled_at=_at(24))
        r2 = Interview(analysis_id=test_analysis.id, round_number=2, scheduled_at=_at(72))
        db_session.add_all([r1, r2])
        db_session.commit()

        # Updating without specifying round must touch ONLY round 2.
        new_when = _at(96)
        updated = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=new_when, interview_type="finale"),
        )
        assert updated is not None
        assert updated.round_number == 2
        assert updated.interview_type == "finale"

        db_session.refresh(r1)
        assert r1.interview_type is None  # round 1 untouched

    def test_get_interview_by_analysis_returns_latest(self, db_session, test_analysis):
        r1 = Interview(analysis_id=test_analysis.id, round_number=1, scheduled_at=_at(24))
        r2 = Interview(analysis_id=test_analysis.id, round_number=2, scheduled_at=_at(72))
        db_session.add_all([r1, r2])
        db_session.commit()

        latest = get_interview_by_analysis(db_session, test_analysis.id)
        assert latest is not None
        assert latest.round_number == 2

    def test_analysis_interview_property_returns_latest(self, db_session, test_analysis):
        r1 = Interview(analysis_id=test_analysis.id, round_number=1, scheduled_at=_at(24))
        r2 = Interview(analysis_id=test_analysis.id, round_number=2, scheduled_at=_at(72))
        db_session.add_all([r1, r2])
        db_session.commit()
        db_session.refresh(test_analysis)

        # Back-compat single accessor used by templates and old call sites.
        assert test_analysis.interview is not None
        assert test_analysis.interview.round_number == 2


class TestCreateNextRound:
    def test_first_round_when_none_exist(self, db_session, test_analysis):
        nr = create_next_round(db_session, test_analysis.id, scheduled_at=_at(24), interview_type="conoscitivo")
        assert nr is not None
        assert nr.round_number == 1

    def test_appends_with_incremented_number(self, db_session, test_analysis):
        create_or_update_interview(db_session, test_analysis.id, InterviewScheduleData(scheduled_at=_at(24)))
        nr = create_next_round(db_session, test_analysis.id, scheduled_at=_at(72), interview_type="tecnico")
        assert nr is not None
        assert nr.round_number == 2


class TestOutcome:
    def test_outcome_defaults_to_null(self, db_session, test_analysis):
        i = create_or_update_interview(db_session, test_analysis.id, InterviewScheduleData(scheduled_at=_at(24)))
        assert i is not None
        assert i.outcome is None

    def test_set_outcome_persists_value(self, db_session, test_analysis):
        i = create_or_update_interview(db_session, test_analysis.id, InterviewScheduleData(scheduled_at=_at(24)))
        assert i is not None

        updated = set_outcome(db_session, i.id, InterviewOutcome.PASSED)
        assert updated is not None
        assert updated.outcome == "passed"

    def test_set_outcome_accepts_string(self, db_session, test_analysis):
        i = create_or_update_interview(db_session, test_analysis.id, InterviewScheduleData(scheduled_at=_at(24)))
        assert i is not None
        updated = set_outcome(db_session, i.id, "rejected")
        assert updated is not None
        assert updated.outcome == "rejected"

    def test_set_outcome_rejects_invalid(self, db_session, test_analysis):
        i = create_or_update_interview(db_session, test_analysis.id, InterviewScheduleData(scheduled_at=_at(24)))
        assert i is not None
        with pytest.raises(ValueError):
            set_outcome(db_session, i.id, "schroedinger")


class TestOutcomeSideEffectsOnAnalysisStatus:
    """The outcome route auto-transitions the parent analysis for terminal outcomes.

    These tests validate the business rule encoded in interview/routes.py:
    - rejected / withdrawn → analysis goes to REJECTED
    - passed / pending → no automatic status change (caller decides next step)
    """

    def test_rejected_transitions_analysis_to_scartato(self, db_session, test_analysis):
        from src.analysis.service import update_status

        i = create_or_update_interview(db_session, test_analysis.id, InterviewScheduleData(scheduled_at=_at(-48)))
        assert i is not None

        # Mimic the route: set outcome then trigger the transition helper.
        updated = set_outcome(db_session, i.id, InterviewOutcome.REJECTED)
        assert updated is not None
        update_status(db_session, test_analysis, AnalysisStatus.REJECTED)
        db_session.commit()
        db_session.refresh(test_analysis)
        assert test_analysis.status == "scartato"

    def test_passed_leaves_status_untouched(self, db_session, test_analysis):
        """Until the caller explicitly schedules a next round or moves to OFFER,
        the analysis stays on whatever status it had (typically 'colloquio').
        """
        test_analysis.status = AnalysisStatus.INTERVIEW.value
        db_session.commit()

        i = create_or_update_interview(db_session, test_analysis.id, InterviewScheduleData(scheduled_at=_at(-48)))
        assert i is not None
        set_outcome(db_session, i.id, InterviewOutcome.PASSED)
        db_session.commit()
        db_session.refresh(test_analysis)
        assert test_analysis.status == "colloquio"


class TestOfferStatus:
    def test_offer_value_exists(self):
        assert AnalysisStatus.OFFER.value == "offerta"

    def test_offer_persists_roundtrip(self, db_session, test_analysis):
        test_analysis.status = AnalysisStatus.OFFER.value
        db_session.commit()
        db_session.refresh(test_analysis)
        assert test_analysis.status == "offerta"
