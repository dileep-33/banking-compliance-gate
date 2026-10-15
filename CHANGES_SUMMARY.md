# Chatbot Guardrails Update Summary

## Files Modified

### 1. `banking_chatbot/chatbot.py`

#### Changes Made:

**Imports & Constants:**
- Removed: `os`, `time`, `defaultdict`, `deque`
- Added: `Callable` type hint
- Removed environment-based rate limit constants (`RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`)
- Changed audit log path: `chatbot_audit.jsonl` → `chatbot_tool_calls.jsonl`
- Added: `SESSION_QUERY_LIMIT = 20` (hardcoded per reference)
- Changed: `_request_history` → `_session_counts` (dict[str, int])

**Function Updates:**

1. **`is_financial_query(user_message: str)`**
   - Added punctuation stripping to properly detect financial keywords
   - Now uses: `re.sub(r"[^\w\s]", " ", user_message.lower()).split()`
   - Fixes: "balance?" now matches "balance" keyword

2. **`pre_response_pii_filter(text: str)`**
   - **Card number masking**: Now retains last 4 digits per PCI DSS requirement
   - Format: `[REDACTED-CARD-****9012]` instead of `[REDACTED_CARD_NUMBER]`
   - Pattern changed from 13-19 digits with optional separators to proper extraction
   - **Account number masking**: Changed from 9-12 digits to 8-12 digits
   - Format: `[REDACTED-ACCT]` instead of `[REDACTED_ACCOUNT_NUMBER]`
   - Reordered patterns to check card numbers first (more specific pattern)

3. **`rate_limit_check(session_id: str, user_message: str)`**
   - **Complete rewrite**: Time-based → Session-based rate limiting
   - Now enforces 20 financial queries per session (not all queries)
   - Only tracks financial queries (determined by `is_financial_query()`)
   - Raises `RuntimeError` when limit exceeded (instead of returning bool)
   - No longer uses sliding time windows

4. **`write_audit_log_entry(event: dict[str, Any])`**
   - **Signature changed**: Takes structured dict instead of string + details
   - Always adds `event_type: "CHATBOT_TOOL_CALL"` to all entries
   - Simplified structure: timestamp + event_type + event fields
   - No longer pre-filters PII (handled upstream in guardrails)

5. **`call_claude(user_message: str)`**
   - Removed `tools` parameter (not needed for basic chatbot)
   - Simplified signature to work as handler function

6. **`run_with_guardrails(user_message: str, session_id: str, handler: Callable[[str], str])`**
   - **Signature changed**: Now matches reference implementation
   - Takes handler function instead of calling Claude directly
   - **Safe error handling**: All exceptions caught and return safe messages
   - Never exposes stack traces, internal errors, or implementation details
   - Rate limit errors return: "Too many financial queries. Please try again later."
   - Other errors return: "An error occurred while processing your request. Please try again."
   - Audit log now records structured events with:
     - `session_id`
     - `financial_query` (boolean)
     - `response_length` (on success)
     - `error` (on failure: "rate_limit_exceeded" or "request_failed")

7. **`handle_message(user_message: str, session_id: str = "default")`**
   - Added `session_id` parameter
   - Now passes `call_claude` as the handler to `run_with_guardrails`

## Files Created

### 1. `banking_chatbot/test_chatbot.py`

Comprehensive test suite with 16 tests covering:

**PII Filtering Tests:**
- Card numbers (13, 16, 19 digits) with last 4 digits retained
- Card numbers with spaces and dashes
- Account numbers (8-12 digits)
- Email addresses
- Social Security Numbers

**Rate Limiting Tests:**
- Non-financial queries not counted
- Financial queries within limit (20)
- Exceeding limit raises error
- Per-session tracking (different sessions have independent limits)

**Audit Logging Tests:**
- Correct structure (timestamp, event_type, session_id, etc.)
- No raw user messages or PII in logs
- Error events logged with error type

**Guardrails Integration Tests:**
- Successful request flow
- PII filtering in responses
- Rate limit error handling (safe message)
- Handler exception handling (safe message)
- No stack traces exposed to users

### 2. `banking_chatbot/demo_guardrails.py`

Demo script showcasing:
- PII filtering on all data types
- Financial query detection
- Full guardrails flow with mock handler
- Rate limiting after 20 financial queries
- Audit log generation

## Compliance Alignment

### PCI DSS Standards (from CLAUDE.md)

1. ✅ **No plaintext card data in logs**: Cards masked to `[REDACTED-CARD-****9012]`
2. ✅ **No hardcoded credentials**: Uses environment variables via `dotenv`
3. ✅ **Input sanitization**: PII filter applied to all responses
4. ✅ **Audit logging for tool calls**: Structured logs to `audit_log/chatbot_tool_calls.jsonl`
5. ✅ **Safe error messages**: No stack traces or internal details to clients

### Reference Implementation Alignment

1. ✅ **Session-based rate limiting**: 20 financial queries per session
2. ✅ **Audit log path**: `audit_log/chatbot_tool_calls.jsonl`
3. ✅ **Structured audit events**: JSON with timestamp, event_type, session_id, etc.
4. ✅ **Handler pattern**: `run_with_guardrails(user_message, session_id, handler)`
5. ✅ **PII filtering**: Card and account number masking
6. ✅ **Financial query detection**: Using keyword set matching

### Enhancements Beyond Reference

1. **Card number masking**: Retains last 4 digits per PCI DSS best practice
2. **Additional PII patterns**: Email and SSN filtering
3. **Comprehensive error handling**: Catches all exceptions, not just RuntimeError
4. **Punctuation handling**: Financial query detection works with punctuation
5. **Test coverage**: 16 comprehensive tests vs. none in reference

## Test Results

All 16 tests pass:
```
test_is_financial_query ............................ PASSED
test_pii_filter_card_numbers ....................... PASSED
test_pii_filter_account_numbers .................... PASSED
test_pii_filter_email .............................. PASSED
test_pii_filter_ssn ................................ PASSED
test_rate_limit_non_financial ...................... PASSED
test_rate_limit_financial_within_limit ............. PASSED
test_rate_limit_financial_exceeds_limit ............ PASSED
test_rate_limit_per_session ........................ PASSED
test_audit_log_structure ........................... PASSED
test_audit_log_no_raw_messages ..................... PASSED
test_run_with_guardrails_success ................... PASSED
test_run_with_guardrails_pii_filtering ............. PASSED
test_run_with_guardrails_rate_limit ................ PASSED
test_run_with_guardrails_handler_exception ......... PASSED
test_run_with_guardrails_no_stack_traces ........... PASSED
```

## Breaking Changes

1. **`run_with_guardrails()` signature**: Changed from `(user_message, *, client_id, tools)` to `(user_message, session_id, handler)`
2. **Rate limiting behavior**: Time-based → Session-based, only counts financial queries
3. **Audit log format**: String events → Structured dictionaries
4. **Audit log path**: Different filename (`chatbot_tool_calls.jsonl`)
5. **Error handling**: Exceptions now return safe messages instead of re-raising

## Migration Notes

Code using the old API needs updates:

**Before:**
```python
response = run_with_guardrails(
    "What is my balance?",
    client_id="user_123",
    tools=[]
)
```

**After:**
```python
def my_handler(message: str) -> str:
    return call_claude(message)

response = run_with_guardrails(
    "What is my balance?",
    session_id="user_123",
    handler=my_handler
)
```

**Or use the convenience function:**
```python
response = handle_message("What is my balance?", session_id="user_123")
```
