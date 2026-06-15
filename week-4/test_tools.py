# week-4/test_tools.py
# Manual validation script — calls every MCP tool and verifies:
#   - correct inputs accepted
#   - correct outputs returned
#   - no internal IDs exposed in results
#   - error handling works
#
# Run with: python -m week-4.test_tools
# ⚠️  This hits your REAL Gmail and Outlook inboxes.

import json
import sys

from mcp_tools.executor import execute_tool, parse_tool_args
from mcp_tools.definitions import ALL_TOOLS, TOOL_NAMES


# ── Display helpers ───────────────────────────────────────────────────────────

def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def print_result(result_str: str):
    # Pretty-print the JSON result the LLM would receive
    try:
        parsed = json.loads(result_str)
        print(json.dumps(parsed, indent=2, default=str))
    except Exception:
        print(result_str)

def check_no_raw_ids(result_str: str, tool_name: str):
    # MG-03 validation — raw Gmail/Outlook IDs are long opaque strings.
    # Gmail message IDs are ~16 hex chars. Outlook IDs start with "AAMk".
    # We flag anything that looks like a raw provider ID in the result.
    parsed = json.loads(result_str)
    result_text = json.dumps(parsed)

    warnings = []

    # Outlook raw message ID pattern
    if "AAMk" in result_text:
        warnings.append("⚠️  Possible raw Outlook message ID found (AAMk...)")

    # If any "id" field exists at email level (not thread_id), flag it
    if "emails" in parsed:
        for email in parsed.get("emails", []):
            if "id" in email:
                warnings.append(f"⚠️  Raw 'id' field exposed in email: {email['id'][:20]}...")

    if warnings:
        for w in warnings:
            print(w)
    else:
        print("  MG-03 check passed — no raw IDs exposed.")


# ── Test 1: gmail_get_messages ────────────────────────────────────────────────

def test_gmail_get_messages():
    print_header("TEST 1 — gmail_get_messages (latest 5 emails)")

    # Simulate exactly what the LLM sends after deciding to call this tool
    tool_name = "gmail_get_messages"
    tool_args = parse_tool_args('{"max_results": 5}')

    print(f"  Tool:  {tool_name}")
    print(f"  Args:  {tool_args}\n")

    result = execute_tool(tool_name, tool_args)
    print_result(result)
    check_no_raw_ids(result, tool_name)


# ── Test 2: gmail_get_messages with query ─────────────────────────────────────

def test_gmail_get_messages_filtered():
    print_header("TEST 2 — gmail_get_messages (unread only)")

    tool_name = "gmail_get_messages"
    tool_args = parse_tool_args('{"max_results": 5, "query": "is:unread"}')

    print(f"  Tool:  {tool_name}")
    print(f"  Args:  {tool_args}\n")

    result = execute_tool(tool_name, tool_args)
    print_result(result)
    check_no_raw_ids(result, tool_name)


# ── Test 3: gmail_get_threads ─────────────────────────────────────────────────

def test_gmail_get_threads():
    print_header("TEST 3 — gmail_get_threads (latest 3 threads)")

    tool_name = "gmail_get_threads"
    tool_args = parse_tool_args('{"max_results": 3}')

    print(f"  Tool:  {tool_name}")
    print(f"  Args:  {tool_args}\n")

    result = execute_tool(tool_name, tool_args)
    print_result(result)


# ── Test 4: gmail_create_draft ────────────────────────────────────────────────

def test_gmail_create_draft():
    print_header("TEST 4 — gmail_create_draft")

    tool_name = "gmail_create_draft"
    tool_args = parse_tool_args(json.dumps({
        "to_email": "test@example.com",
        "subject":  "Test Draft from Mail Genie",
        "body":     "Hi,\n\nThis is a test draft created by the Mail Genie MCP tool layer.\n\nBest regards"
    }))

    print(f"  Tool:  {tool_name}")
    print(f"  Args:  {tool_args}\n")

    result = execute_tool(tool_name, tool_args)
    print_result(result)

    # Verify draft ID is hidden (MG-03)
    parsed = json.loads(result)
    if "draft_id" in parsed or "id" in parsed:
        print("  ⚠️  MG-03 FAIL — raw draft ID exposed in result")
    else:
        print("  MG-03 check passed — draft ID hidden from result.")


# ── Test 5: outlook_get_messages ──────────────────────────────────────────────

def test_outlook_get_messages():
    print_header("TEST 5 — outlook_get_messages (latest 5 emails)")

    tool_name = "outlook_get_messages"
    tool_args = parse_tool_args('{"max_results": 5}')

    print(f"  Tool:  {tool_name}")
    print(f"  Args:  {tool_args}\n")

    result = execute_tool(tool_name, tool_args)
    print_result(result)
    check_no_raw_ids(result, tool_name)


# ── Test 6: outlook_create_draft ──────────────────────────────────────────────

def test_outlook_create_draft():
    print_header("TEST 6 — outlook_create_draft")

    tool_name = "outlook_create_draft"
    tool_args = parse_tool_args(json.dumps({
        "to_email": "test@example.com",
        "subject":  "Test Draft from Mail Genie (Outlook)",
        "body":     "Hi,\n\nThis is a test draft created by the Mail Genie MCP tool layer via Outlook.\n\nBest regards"
    }))

    print(f"  Tool:  {tool_name}")
    print(f"  Args:  {tool_args}\n")

    result = execute_tool(tool_name, tool_args)
    print_result(result)

    parsed = json.loads(result)
    if "draft_id" in parsed or "id" in parsed:
        print("  ⚠️  MG-03 FAIL — raw draft ID exposed in result")
    else:
        print("  MG-03 check passed — draft ID hidden from result.")


# ── Test 7: Error handling — unknown tool ─────────────────────────────────────

def test_unknown_tool():
    print_header("TEST 7 — Error handling (unknown tool name)")

    # Simulate LLM hallucinating a tool name that doesn't exist
    tool_name = "gmail_search_emails"   # doesn't exist
    tool_args = {}

    print(f"  Tool:  {tool_name} (intentionally invalid)\n")

    result = execute_tool(tool_name, tool_args)
    print_result(result)

    parsed = json.loads(result)
    if "error" in parsed:
        print("  Error handling passed — unknown tool caught cleanly.")
    else:
        print("  ⚠️  Error handling FAILED — should have returned an error.")


# ── Test 8: Error handling — wrong arguments ──────────────────────────────────

def test_wrong_args():
    print_header("TEST 8 — Error handling (wrong argument name)")

    # Simulate LLM passing wrong parameter name
    tool_name = "gmail_get_messages"
    tool_args = {"limit": 5}   # wrong — should be "max_results"

    print(f"  Tool:  {tool_name}")
    print(f"  Args:  {tool_args} (intentionally wrong)\n")

    result = execute_tool(tool_name, tool_args)
    print_result(result)

    parsed = json.loads(result)
    if "error" in parsed:
        print("  Error handling passed — bad args caught cleanly.")
    else:
        # gmail_get_messages has no required args so it may still run with defaults
        print("  Tool ran with defaults (acceptable — no required params).")


# ── Run all tests ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nMail Genie — MCP Tool Validation")
    print(f"Testing {len(TOOL_NAMES)} tools against real inboxes\n")

    # Read-only tests first (safe to run any time)
    test_gmail_get_messages()
    test_gmail_get_messages_filtered()
    test_gmail_get_threads()
    test_outlook_get_messages()

    # Write tests — create drafts only, never send (safe)
    test_gmail_create_draft()
    test_outlook_create_draft()

    # Error handling tests
    test_unknown_tool()
    test_wrong_args()

    print("\n" + "=" * 60)
    print("  Validation complete.")
    print("  Check above for any ⚠️  warnings before Week 5.")
    print("=" * 60 + "\n")