"""
Demo script to test guardrails functionality without requiring API access.
"""

from chatbot import pre_response_pii_filter, is_financial_query, run_with_guardrails


def mock_handler(message: str) -> str:
    """Simple mock handler for demonstration."""
    if "balance" in message.lower():
        return "Your account 123456789 balance is $5,000. Card 4532123456789012 on file."
    return f"I received your message: {message}"


def main():
    print("=== Banking Chatbot Guardrails Demo ===\n")

    # Demo 1: PII Filtering
    print("1. PII Filtering Demo")
    test_text = "Card 4532123456789012, account 123456789, email user@test.com, SSN 123-45-6789"
    filtered = pre_response_pii_filter(test_text)
    print(f"   Original: {test_text}")
    print(f"   Filtered: {filtered}\n")

    # Demo 2: Financial Query Detection
    print("2. Financial Query Detection")
    queries = [
        "What is my balance?",
        "Hello, how are you?",
        "I need to transfer money",
    ]
    for query in queries:
        is_financial = is_financial_query(query)
        print(f"   '{query}' → Financial: {is_financial}")
    print()

    # Demo 3: Guardrails Integration
    print("3. Guardrails Integration Demo")

    # Non-financial query
    result = run_with_guardrails(
        "Hello, what services do you offer?",
        "demo_session_1",
        mock_handler
    )
    print(f"   Response: {result}\n")

    # Financial query with PII filtering
    result = run_with_guardrails(
        "What is my balance?",
        "demo_session_1",
        mock_handler
    )
    print(f"   Response: {result}\n")

    # Demo 4: Rate Limiting
    print("4. Rate Limiting Demo (20 financial queries per session)")
    for i in range(1, 23):
        result = run_with_guardrails(
            "What is my balance?",
            "demo_session_2",
            mock_handler
        )
        if "Too many" in result:
            print(f"   Request {i}: Rate limited ✓")
            break
        elif i <= 20:
            print(f"   Request {i}: Success ✓")

    print("\n=== Demo Complete ===")
    print("Check audit_log/chatbot_tool_calls.jsonl for audit entries")


if __name__ == "__main__":
    main()
