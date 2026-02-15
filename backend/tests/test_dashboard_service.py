"""Tests for dashboard service."""

from src.dashboard.service import (
    add_spending,
    get_or_create_settings,
    get_spending,
    remove_spending,
    update_budget,
)


class TestGetOrCreateSettings:
    def test_creates_settings_if_missing(self, db_session):
        s = get_or_create_settings(db_session)
        db_session.commit()
        assert s.id == 1
        assert s.anthropic_budget == 0.0

    def test_returns_existing_settings(self, db_session):
        s1 = get_or_create_settings(db_session)
        s1.anthropic_budget = 10.0
        db_session.commit()

        s2 = get_or_create_settings(db_session)
        assert s2.anthropic_budget == 10.0


class TestAddSpending:
    def test_adds_analysis_spending(self, db_session):
        add_spending(db_session, 0.005, 1000, 500, is_analysis=True)
        db_session.commit()

        spending = get_spending(db_session)
        assert spending["total_cost_usd"] == 0.005
        assert spending["total_analyses"] == 1
        assert spending["total_tokens_input"] == 1000
        assert spending["total_tokens_output"] == 500

    def test_adds_cover_letter_spending(self, db_session):
        add_spending(db_session, 0.001, 200, 100, is_analysis=False)
        db_session.commit()

        s = get_or_create_settings(db_session)
        assert s.total_cover_letters == 1

    def test_accumulates_spending(self, db_session):
        add_spending(db_session, 0.005, 1000, 500)
        add_spending(db_session, 0.010, 2000, 1000)
        db_session.commit()

        spending = get_spending(db_session)
        assert spending["total_cost_usd"] == 0.015
        assert spending["total_analyses"] == 2


class TestRemoveSpending:
    def test_removes_spending(self, db_session):
        add_spending(db_session, 0.010, 2000, 1000)
        db_session.commit()

        remove_spending(db_session, 0.005, 1000, 500)
        db_session.commit()

        spending = get_spending(db_session)
        assert spending["total_cost_usd"] == 0.005
        assert spending["total_tokens_input"] == 1000

    def test_does_not_go_negative(self, db_session):
        remove_spending(db_session, 999.0, 999999, 999999)
        db_session.commit()

        spending = get_spending(db_session)
        assert spending["total_cost_usd"] == 0.0
        assert spending["total_tokens_input"] == 0


class TestUpdateBudget:
    def test_sets_budget(self, db_session):
        result = update_budget(db_session, 25.0)
        db_session.commit()
        assert result == 25.0

        spending = get_spending(db_session)
        assert spending["budget"] == 25.0

    def test_clamps_negative_to_zero(self, db_session):
        result = update_budget(db_session, -5.0)
        db_session.commit()
        assert result == 0.0


class TestGetSpending:
    def test_calculates_remaining(self, db_session):
        update_budget(db_session, 10.0)
        add_spending(db_session, 3.0, 100000, 50000)
        db_session.commit()

        spending = get_spending(db_session)
        assert spending["remaining"] == 7.0

    def test_remaining_none_when_no_budget(self, db_session):
        spending = get_spending(db_session)
        assert spending["remaining"] is None
