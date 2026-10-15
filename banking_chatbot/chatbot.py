
"""
Module 6 Project 3 — Banking Chatbot with PCI DSS guardrails.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from llm_client import get_llm_client, resolve_model

load_dotenv()

FINANCIAL_KEYWORDS = frozenset({
    "balance", "transfer", "account", "statement", "loan",
    "credit", "debit", "transaction", "payment",
})

AUDIT_LOG = Path(__file__).resolve().parent.parent / "audit_log" / "chatbot_tool_calls.jsonl"
SESSION_QUERY_LIMIT = 20

_session_counts: dict[str, int] = {}


def is_financial_query(user_message: str) -> bool:
    """Return True if the message looks like a financial query."""
    tokens = set(re.sub(r"[^\w\s]", " ", user_message.lower()).split())
    return bool(tokens & FINANCIAL_KEYWORDS)


def pre_response_pii_filter(text: str) -> str:
    """Mask common sensitive identifiers before text is returned or logged."""
    def mask_card_number(match: re.Match) -> str:
        digits = re.sub(r"[^0-9]", "", match.group(0))
        if 13 <= len(digits) <= 19:
            return f"[REDACTED-CARD-****{digits[-4:]}]"
        return match.group(0)

    text = re.sub(r"\b(?:\d[ -]*?){13,19}\b", mask_card_number, text)
    text = re.sub(r"\b\d{8,12}\b", "[REDACTED-ACCT]", text)
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED-EMAIL]", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED-SSN]", text)
    return text


def rate_limit_check(session_id: str, user_message: str) -> None:
    """Enforce limit of 20 financial queries per session."""
    if not is_financial_query(user_message):
        return

    count = _session_counts.get(session_id, 0) + 1
    _session_counts[session_id] = count

    if count > SESSION_QUERY_LIMIT:
        raise RuntimeError(
            f"Rate limit exceeded: {count} financial queries in session {session_id}"
        )


def write_audit_log_entry(event: dict[str, Any]) -> None:
    """Append a structured JSON audit event without recording raw messages or PII."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "CHATBOT_TOOL_CALL",
        **event,
    }

    with AUDIT_LOG.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record) + "\n")


def call_claude(user_message: str) -> str:
    """Send a user message to Claude and return its text response."""
    client = get_llm_client()
    response = client.messages.create(
        model=resolve_model("claude-sonnet-4-5"),
        max_tokens=1024,
        messages=[{"role": "user", "content": user_message}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def run_with_guardrails(
    user_message: str,
    session_id: str,
    handler: Callable[[str], str],
) -> str:
    """Apply rate limits, filter sensitive data, audit interactions, and handle errors safely."""
    try:
        rate_limit_check(session_id, user_message)
        raw_response = handler(user_message)
        filtered_response = pre_response_pii_filter(raw_response)

        write_audit_log_entry({
            "session_id": session_id,
            "financial_query": is_financial_query(user_message),
            "response_length": len(filtered_response),
        })

        return filtered_response

    except RuntimeError as e:
        if "Rate limit exceeded" in str(e):
            write_audit_log_entry({
                "session_id": session_id,
                "error": "rate_limit_exceeded",
            })
            return "Too many financial queries. Please try again later."
        write_audit_log_entry({
            "session_id": session_id,
            "error": "request_failed",
        })
        return "An error occurred while processing your request. Please try again."

    except Exception:
        write_audit_log_entry({
            "session_id": session_id,
            "error": "request_failed",
        })
        return "An error occurred while processing your request. Please try again."


def handle_message(user_message: str, session_id: str = "default") -> str:
    """Handle a chatbot request through the compliance guardrails."""
    return run_with_guardrails(user_message, session_id, call_claude)


if __name__ == "__main__":
    print(handle_message("What services does Heritage National Bank offer?"))
