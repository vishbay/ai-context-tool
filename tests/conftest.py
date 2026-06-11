"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_audit_db(tmp_path, monkeypatch):
    """Point the audit event store at a per-test temp file.

    Without this, audit tests would ingest their synthetic fixture transcripts
    into the user's real ~/.local/share/cram-ai/audit.db.
    """
    monkeypatch.setenv('CRAM_AUDIT_DB', str(tmp_path / 'audit-test.db'))
