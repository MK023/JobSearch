"""Tests for contacts service."""

import uuid

from src.contacts.service import create_contact, delete_contact_by_id, get_contacts_for_analysis


class TestCreateContact:
    def test_creates_contact(self, db_session, test_analysis):
        contact = create_contact(
            db_session,
            analysis_id=str(test_analysis.id),
            name="John Recruiter",
            email="john@company.com",
            phone="+1234567890",
            company="TestCorp",
            linkedin_url="https://linkedin.com/in/john",
            notes="Met at conference",
        )
        db_session.commit()
        assert contact.name == "John Recruiter"
        assert contact.email == "john@company.com"
        assert contact.analysis_id == test_analysis.id

    def test_creates_contact_without_analysis(self, db_session):
        contact = create_contact(
            db_session,
            analysis_id=None,
            name="Jane",
            email="jane@test.com",
            phone="",
            company="",
            linkedin_url="",
            notes="",
        )
        db_session.commit()
        assert contact.analysis_id is None
        assert contact.name == "Jane"


class TestGetContactsForAnalysis:
    def test_returns_contacts(self, db_session, test_analysis):
        create_contact(db_session, str(test_analysis.id), "A", "a@t.com", "", "", "", "")
        create_contact(db_session, str(test_analysis.id), "B", "b@t.com", "", "", "", "")
        db_session.commit()

        contacts = get_contacts_for_analysis(db_session, str(test_analysis.id))
        assert len(contacts) == 2

    def test_returns_empty_for_no_contacts(self, db_session, test_analysis):
        contacts = get_contacts_for_analysis(db_session, str(test_analysis.id))
        assert contacts == []

    def test_returns_empty_for_invalid_uuid(self, db_session):
        contacts = get_contacts_for_analysis(db_session, "not-a-uuid")
        assert contacts == []


class TestDeleteContact:
    def test_deletes_existing_contact(self, db_session, test_analysis):
        contact = create_contact(db_session, str(test_analysis.id), "Del", "d@t.com", "", "", "", "")
        db_session.commit()

        result = delete_contact_by_id(db_session, str(contact.id))
        db_session.commit()
        assert result is True

        contacts = get_contacts_for_analysis(db_session, str(test_analysis.id))
        assert len(contacts) == 0

    def test_returns_false_for_missing(self, db_session):
        result = delete_contact_by_id(db_session, str(uuid.uuid4()))
        assert result is False

    def test_returns_false_for_invalid_uuid(self, db_session):
        result = delete_contact_by_id(db_session, "bad-id")
        assert result is False
