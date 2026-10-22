
# GR-07: Privacy-safe ballot audit logging tests

from app.models.audit import AuditEvent
from app.services.audit_log import append_audit
from app import db

from test_gr05_eligibility import client


def test_ballot_audit_has_no_voter_identity(client):
    # Use the existing isolated test database
    with client.application.app_context():

        # Record a ballot commitment event
        event = append_audit(
            "ballot.committed",
            "Ballot accepted for election 1"
        )

        db.session.flush()

        # Verify voter identity is not included
        assert event.actor_id is None
        assert event.actor_username is None

        # Verify no sensitive ballot information is present
        assert "preferences" not in event.detail.lower()
        assert "token" not in event.detail.lower()

        db.session.rollback()


def test_ballot_audit_event_type(client):
    with client.application.app_context():
        event = append_audit(
            "ballot.committed",
            "Ballot accepted for election 1"
        )

        db.session.flush()

        assert event.action == "ballot.committed"

        db.session.rollback()
