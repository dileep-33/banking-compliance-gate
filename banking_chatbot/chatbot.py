
"""
Module 6 Project 3 — Banking Chatbot with PCI DSS guardrails.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from llm_client import get_llm_client, resolve_model

load_dotenv()

FINANCIAL_KEYWORDS = frozenset({
    "balance", "transfer", "account", "statement", "loan",
    "credit", "debit", "transaction", "payment",
})

AUDIT_LOG = Path(__file__).resolve().parent.parent / "audit_log" / "chatbot_audit.jsonl"
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

_request_history: dict[str, deque[float]] = defaultdict(deque)


def is_financial_query(user_message: str) -> bool:
    """Return True if the message looks like a financial query."""
    tokens = set(user_message.lower().split())
    return bool(tokens & FINANCIAL_KEYWORDS)


def pre_response_pii_filter(text: str) -> str:
    """Mask common sensitive identifiers before text is returned or logged."""
    patterns = [
        (r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]"),
        (r"\b(?:\d[ -]*?){13,19}\b", "[REDACTED_CARD_NUMBER]"),
        (r"\b\d{9,12}\b", "[REDACTED_ACCOUNT_NUMBER]"),
        (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def rate_limit_check(
    client_id: str = "default",
    *,
    now: float | None = None,
) -> bool:
    """Return True when a request is allowed under the configured rate limit."""
    if RATE_LIMIT_REQUESTS < 1 or RATE_LIMIT_WINDOW_SECONDS < 1:
        raise ValueError("Rate-limit settings must be positive")

    current_time = time.monotonic() if now is None else now
    history = _request_history[client_id]

    while history and current_time - history[0] >= RATE_LIMIT_WINDOW_SECONDS:
        history.popleft()

    if len(history) >= RATE_LIMIT_REQUESTS:
        return False

    history.append(current_time)
    return True


def write_audit_log_entry(
    event: str,
    *,
    client_id: str = "default",
    details: dict[str, Any] | None = None,
) -> None:
    """Append a JSON audit event without recording raw user messages."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": pre_response_pii_filter(event),
        "client_id": pre_response_pii_filter(client_id),
        "details": pre_response_pii_filter(
            json.dumps(details or {}, default=str)
        ),
    }

    with AUDIT_LOG.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record) + "\n")


def call_claude(
    user_message: str,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """Send a user message to Claude and return its text response."""
    client = get_llm_client()
    response = client.messages.create(
        model=resolve_model("claude-sonnet-4-5"),
        max_tokens=1024,
        tools=tools or [],
        messages=[{"role": "user", "content": user_message}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def run_with_guardrails(
    user_message: str,
    *,
    client_id: str = "default",
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """Apply request limits, filter sensitive data, and audit the interaction."""
    if not isinstance(user_message, str) or not user_message.strip():
        raise ValueError("user_message must be a non-empty string")

    if not rate_limit_check(client_id):
        write_audit_log_entry("rate_limit_exceeded", client_id=client_id)
        return "Too many requests. Please try again later."

    safe_message = pre_response_pii_filter(user_message)
    write_audit_log_entry("request_received", client_id=client_id)

    try:
        response = call_claude(safe_message, tools=tools)
        safe_response = pre_response_pii_filter(response)
        write_audit_log_entry("response_generated", client_id=client_id)
        return safe_response
    except Exception:
        write_audit_log_entry("request_failed", client_id=client_id)
        raise


def handle_message(user_message: str) -> str:
    """Handle a chatbot request through the compliance guardrails."""
    return run_with_guardrails(user_message)


if __name__ == "__main__":
    print(handle_message("What services does Heritage National Bank offer?"))
