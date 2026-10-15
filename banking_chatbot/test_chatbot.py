"""
Test suite for banking chatbot guardrails.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from chatbot import (
    is_financial_query,
    pre_response_pii_filter,
    rate_limit_check,
    run_with_guardrails,
    write_audit_log_entry,
    _session_counts,
    SESSION_QUERY_LIMIT,
    AUDIT_LOG,
)


def test_is_financial_query():
    """Test financial query detection."""
    assert is_financial_query("What is my account balance?")
    assert is_financial_query("I need to transfer money")
    assert is_financial_query("Can I apply for a loan?")
    assert is_financial_query("Show me my statement")
    assert not is_financial_query("What is the weather today?")
    assert not is_financial_query("Hello, how are you?")


def test_pii_filter_card_numbers():
    """Test card number masking with last 4 digits retained."""
    # 16-digit card number
    result = pre_response_pii_filter("Your card 4532123456789012 was charged")
    assert "[REDACTED-CARD-****9012]" in result
    assert "4532123456789012" not in result

    # Card with spaces
    result = pre_response_pii_filter("Card number: 4532 1234 5678 9012")
    assert "[REDACTED-CARD-****9012]" in result

    # Card with dashes
    result = pre_response_pii_filter("Card: 4532-1234-5678-9012")
    assert "[REDACTED-CARD-****9012]" in result

    # 13-digit card number
    result = pre_response_pii_filter("Amex card 371449635398431")
    assert "[REDACTED-CARD-****8431]" in result

    # 19-digit card number
    result = pre_response_pii_filter("Card 6011000990139424123")
    assert "[REDACTED-CARD-****4123]" in result


def test_pii_filter_account_numbers():
    """Test account number masking."""
    result = pre_response_pii_filter("Account 123456789 has been debited")
    assert "[REDACTED-ACCT]" in result
    assert "123456789" not in result

    result = pre_response_pii_filter("Transfer from 12345678 to 987654321")
    assert result.count("[REDACTED-ACCT]") == 2


def test_pii_filter_email():
    """Test email masking."""
    result = pre_response_pii_filter("Contact us at support@bank.com")
    assert "[REDACTED-EMAIL]" in result
    assert "support@bank.com" not in result


def test_pii_filter_ssn():
    """Test SSN masking."""
    result = pre_response_pii_filter("SSN: 123-45-6789")
    assert "[REDACTED-SSN]" in result
    assert "123-45-6789" not in result


def test_rate_limit_non_financial():
    """Test that non-financial queries are not rate limited."""
    session_id = "test_session_1"
    _session_counts.clear()

    for i in range(25):
        rate_limit_check(session_id, "Hello, how are you?")

    assert session_id not in _session_counts or _session_counts[session_id] == 0


def test_rate_limit_financial_within_limit():
    """Test financial queries within the rate limit."""
    session_id = "test_session_2"
    _session_counts.clear()

    for i in range(SESSION_QUERY_LIMIT):
        rate_limit_check(session_id, "What is my balance?")

    assert _session_counts[session_id] == SESSION_QUERY_LIMIT


def test_rate_limit_financial_exceeds_limit():
    """Test that exceeding financial query limit raises error."""
    session_id = "test_session_3"
    _session_counts.clear()

    for i in range(SESSION_QUERY_LIMIT):
        rate_limit_check(session_id, "What is my balance?")

    with pytest.raises(RuntimeError, match="Rate limit exceeded"):
        rate_limit_check(session_id, "What is my balance?")


def test_rate_limit_per_session():
    """Test that rate limits are tracked per session."""
    _session_counts.clear()

    for i in range(SESSION_QUERY_LIMIT):
        rate_limit_check("session_a", "What is my balance?")
        rate_limit_check("session_b", "What is my balance?")

    assert _session_counts["session_a"] == SESSION_QUERY_LIMIT
    assert _session_counts["session_b"] == SESSION_QUERY_LIMIT


def test_audit_log_structure(tmp_path, monkeypatch):
    """Test that audit logs have correct structure."""
    audit_file = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr("chatbot.AUDIT_LOG", audit_file)

    write_audit_log_entry({
        "session_id": "test_session",
        "financial_query": True,
        "response_length": 100,
    })

    assert audit_file.exists()
    with open(audit_file, "r") as f:
        log_entry = json.loads(f.readline())

    assert "timestamp" in log_entry
    assert log_entry["event_type"] == "CHATBOT_TOOL_CALL"
    assert log_entry["session_id"] == "test_session"
    assert log_entry["financial_query"] is True
    assert log_entry["response_length"] == 100


def test_audit_log_no_raw_messages(tmp_path, monkeypatch):
    """Test that audit logs don't contain raw user messages."""
    audit_file = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr("chatbot.AUDIT_LOG", audit_file)

    write_audit_log_entry({
        "session_id": "test_session",
        "financial_query": True,
        "response_length": 50,
    })

    with open(audit_file, "r") as f:
        content = f.read()

    # Audit log should not contain user message content
    assert "user_message" not in content.lower()
    assert "raw_message" not in content.lower()


def test_run_with_guardrails_success(tmp_path, monkeypatch):
    """Test successful request through guardrails."""
    audit_file = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr("chatbot.AUDIT_LOG", audit_file)
    _session_counts.clear()

    mock_handler = MagicMock(return_value="Your balance is $1000")

    result = run_with_guardrails(
        "What is my balance?",
        "test_session",
        mock_handler
    )

    assert result == "Your balance is $1000"
    mock_handler.assert_called_once_with("What is my balance?")

    # Check audit log
    with open(audit_file, "r") as f:
        log_entry = json.loads(f.readline())

    assert log_entry["session_id"] == "test_session"
    assert log_entry["financial_query"] is True


def test_run_with_guardrails_pii_filtering(tmp_path, monkeypatch):
    """Test PII filtering in responses."""
    audit_file = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr("chatbot.AUDIT_LOG", audit_file)
    _session_counts.clear()

    mock_handler = MagicMock(
        return_value="Your card 4532123456789012 will be charged"
    )

    result = run_with_guardrails(
        "Process my payment",
        "test_session",
        mock_handler
    )

    assert "4532123456789012" not in result
    assert "[REDACTED-CARD-****9012]" in result


def test_run_with_guardrails_rate_limit(tmp_path, monkeypatch):
    """Test rate limit handling returns safe error message."""
    audit_file = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr("chatbot.AUDIT_LOG", audit_file)
    _session_counts.clear()

    mock_handler = MagicMock(return_value="Balance: $1000")

    # Exhaust rate limit
    for i in range(SESSION_QUERY_LIMIT):
        run_with_guardrails("What is my balance?", "test_session", mock_handler)

    # Next request should return safe error message
    result = run_with_guardrails(
        "What is my balance?",
        "test_session",
        mock_handler
    )

    assert result == "Too many financial queries. Please try again later."
    assert "RuntimeError" not in result
    assert "Traceback" not in result


def test_run_with_guardrails_handler_exception(tmp_path, monkeypatch):
    """Test that handler exceptions return safe error messages."""
    audit_file = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr("chatbot.AUDIT_LOG", audit_file)
    _session_counts.clear()

    mock_handler = MagicMock(side_effect=ValueError("Internal API error"))

    result = run_with_guardrails(
        "What is my balance?",
        "test_session",
        mock_handler
    )

    assert result == "An error occurred while processing your request. Please try again."
    assert "ValueError" not in result
    assert "Internal API error" not in result
    assert "Traceback" not in result

    # Check error was logged
    with open(audit_file, "r") as f:
        log_entry = json.loads(f.readline())

    assert log_entry["error"] == "request_failed"


def test_run_with_guardrails_no_stack_traces(tmp_path, monkeypatch):
    """Test that exceptions never expose stack traces to users."""
    audit_file = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr("chatbot.AUDIT_LOG", audit_file)
    _session_counts.clear()

    # Test various exception types
    exceptions = [
        ValueError("Database connection failed"),
        RuntimeError("API timeout"),
        Exception("Unknown error"),
    ]

    for exc in exceptions:
        _session_counts.clear()
        mock_handler = MagicMock(side_effect=exc)

        result = run_with_guardrails(
            "Hello",
            "test_session",
            mock_handler
        )

        # Verify no internal details leaked
        assert "Traceback" not in result
        assert "Exception" not in result
        assert "Error" not in result or result == "An error occurred while processing your request. Please try again."
        assert str(exc) not in result
