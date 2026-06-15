# mcp_tools/executor.py
# The dispatcher — receives a tool_call from the LLM and routes it
# to the correct Python function.
#
# This is the ONLY file the agent imports from mcp_tools at runtime.
# The agent calls: execute_tool(tool_name, tool_args)
# The executor handles everything else.
#
# Design: a dispatch map (dict) instead of if/elif chains.
# Adding a new tool = one line in TOOL_REGISTRY. Nothing else changes.


import json

# Import every tool function we've built
from mcp_tools.gmail_tools import (
    gmail_get_messages,
    gmail_create_draft,
    gmail_send_message,
    gmail_get_threads,
)
from mcp_tools.outlook_tools import (
    outlook_get_messages,
    outlook_create_draft,
    outlook_send_message,
)

# Import the valid tool name set for upfront validation
from mcp_tools.definitions import TOOL_NAMES


# ── Dispatch map ──────────────────────────────────────────────────────────────
# Maps every tool name string → its Python function.
# When the LLM returns tool_call.function.name = "gmail_get_messages",
# the executor looks it up here and calls the function directly.
#
# Key insight: the tool functions all accept **kwargs so we can unpack
# the LLM's argument dict directly without knowing the parameter names.
# Adding a new tool: add one entry here + one definition in definitions.py.

TOOL_REGISTRY = {
    "gmail_get_messages":   gmail_get_messages,
    "gmail_create_draft":   gmail_create_draft,
    "gmail_send_message":   gmail_send_message,
    "gmail_get_threads":    gmail_get_threads,
    "outlook_get_messages": outlook_get_messages,
    "outlook_create_draft": outlook_create_draft,
    "outlook_send_message": outlook_send_message,
}


# ── execute_tool() ────────────────────────────────────────────────────────────
# The single function the agent calls for every tool_call the LLM returns.
#
# Parameters:
#   tool_name  — the string from tool_call.function.name
#                e.g. "gmail_get_messages"
#   tool_args  — the dict from tool_call.function.arguments (already parsed)
#                e.g. {"max_results": 5, "query": "is:unread"}
#
# Returns:
#   A string — always. Either the tool's JSON result or an error JSON string.
#   The agent appends this string as a "tool" role message back to the LLM.
#
# Why always a string?
#   The OpenAI API requires tool result content to be a string.
#   Our tool functions already return _serialise() strings, so this is consistent.

def execute_tool(tool_name: str, tool_args: dict) -> str:

    # ── Step 1: Validate the tool name ────────────────────────────────────────
    # Guard against hallucinated tool names — the LLM occasionally invents
    # tool names that don't exist (e.g. "gmail_search_emails" instead of
    # "gmail_get_messages"). We catch that here before it causes a KeyError.

    if tool_name not in TOOL_NAMES:
        return json.dumps({
            "error": f"Unknown tool '{tool_name}'. "
                     f"Available tools: {sorted(TOOL_NAMES)}"
        })

    # ── Step 2: Look up the function ──────────────────────────────────────────
    # TOOL_REGISTRY maps name → function object.
    # This is equivalent to calling the function directly but determined at runtime.

    tool_fn = TOOL_REGISTRY[tool_name]

    # ── Step 3: Execute with error isolation ──────────────────────────────────
    # We wrap the call in try/except so a crash in one tool never
    # crashes the entire agent loop. The agent receives an error string,
    # the LLM reads it, and can inform the user gracefully.

    try:
        # **tool_args unpacks the dict as keyword arguments.
        # e.g. tool_args = {"max_results": 5, "query": "is:unread"}
        # becomes: gmail_get_messages(max_results=5, query="is:unread")
        #
        # This works because every tool function signature matches
        # exactly the parameter names defined in definitions.py.
        result = tool_fn(**tool_args)
        return result

    except TypeError as e:
        # TypeError means the LLM passed wrong/unexpected parameter names.
        # Return a clear error so we can debug the schema mismatch.
        return json.dumps({
            "error":     f"Tool '{tool_name}' received unexpected arguments.",
            "detail":    str(e),
            "args_sent": tool_args
        })

    except Exception as e:
        # Catch-all for any other runtime error in the tool function itself.
        return json.dumps({
            "error":  f"Tool '{tool_name}' raised an exception.",
            "detail": str(e)
        })


# ── parse_tool_args() ─────────────────────────────────────────────────────────
# Helper the agent uses to safely parse tool_call.function.arguments.
#
# The OpenAI API returns arguments as a JSON STRING, not a dict.
# e.g. tool_call.function.arguments = '{"max_results": 5, "query": "is:unread"}'
#
# The agent must parse this string before passing to execute_tool().
# This helper does that safely with a fallback to empty dict on failure.

def parse_tool_args(arguments_str: str) -> dict:
    try:
        return json.loads(arguments_str)
    except json.JSONDecodeError:
        # Malformed JSON from LLM — rare but possible
        # Return empty dict so the tool runs with its defaults
        return {}


# ── Quick self-test ───────────────────────────────────────────────────────────
# Run with: python -m mcp_tools.executor
# Verifies the registry is complete and every name in TOOL_NAMES has a function.

if __name__ == "__main__":
    print("MCP Tool Registry — Validation\n")
    print(f"  Tools defined:    {len(TOOL_NAMES)}")
    print(f"  Tools registered: {len(TOOL_REGISTRY)}\n")

    # Check every defined tool has a registered function
    all_ok = True
    for name in sorted(TOOL_NAMES):
        registered = name in TOOL_REGISTRY
        status     = "OK" if registered else "MISSING"
        print(f"  [{status}] {name}")
        if not registered:
            all_ok = False

    # Check no extra functions are registered without a definition
    for name in sorted(TOOL_REGISTRY):
        if name not in TOOL_NAMES:
            print(f"  [EXTRA] {name} — registered but no definition found")
            all_ok = False

    print()
    if all_ok:
        print("  All tools registered correctly.")
    else:
        print("  Fix mismatches above before running the agent.")