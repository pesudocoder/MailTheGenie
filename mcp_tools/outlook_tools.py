# mcp_tools/outlook_tools.py
# Outlook tool implementations — the actual Python functions that run
# when the LLM calls an Outlook tool by name.
#
# Simpler than gmail_tools.py because:
#   - outlook_connector.py handles its own auth internally (get_access_token()
#     is called inside every connector function — we don't manage a service object)
#   - No query filtering needed for the prototype (Outlook Graph API filtering
#     is added in Week 5 when we build the full agent)
#   - Only 3 tools: get_messages, create_draft, send_message


import json
from connectors.outlook_connector import (
    get_messages,    # fetches emails — handles auth internally
    create_draft,    # creates draft — handles auth internally
    send_message,    # sends email — handles auth internally
)


# ── Helper: serialise datetime objects ────────────────────────────────────────
# Identical to the one in gmail_tools.py — each tool file is self-contained
# so we don't create a shared dependency just for one helper.
# datetime objects in outlook emails (received_at) must be converted to
# strings before json.dumps() — default=str handles this automatically.

def _serialise(data) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)


# ── outlook_get_messages ──────────────────────────────────────────────────────
# Wraps: get_messages() from outlook_connector.py
#
# The connector already returns normalised dicts (via normalise_outlook_email)
# with these keys: id, provider, sender, subject, body, received_at, is_read, thread_id
#
# We strip the raw Outlook message ID (the "id" field) before returning
# to the LLM — it's a long opaque string like "AAMkAGVmMDEzMTM4..." (MG-03).
# We keep thread_id (conversationId) because the agent needs it for replies.

def outlook_get_messages(max_results: int = 10) -> str:
    try:
        # get_messages() calls get_access_token() internally —
        # silent refresh if token is cached, browser popup only on first run
        emails = get_messages(max_results=max_results)

        # Strip internal Outlook message ID — never shown to user (MG-03)
        # Keep everything else — the LLM needs sender, subject, body for triage
        safe_emails = []
        for e in emails:
            safe_emails.append({
                "sender":      e.get("sender", "Unknown"),
                "subject":     e.get("subject", "(no subject)"),
                "body":        e.get("body", ""),
                "received_at": e.get("received_at", ""),   # datetime → str via _serialise
                "is_read":     e.get("is_read", True),
                "thread_id":   e.get("thread_id", ""),     # kept for reply use
                "provider":    "outlook"
            })
            # Note: "id" (raw Outlook message ID) is intentionally excluded here

        return _serialise({
            "provider": "outlook",
            "count":    len(safe_emails),
            "emails":   safe_emails
        })

    except Exception as e:
        return _serialise({"error": f"outlook_get_messages failed: {str(e)}"})


# ── outlook_create_draft ──────────────────────────────────────────────────────
# Wraps: create_draft() from outlook_connector.py
#
# The connector's create_draft() already returns a user-friendly dict
# and hides the internal Outlook draft ID (MG-03 is handled in the connector).
# We just call it, serialise the result, and return.
#
# Unlike Gmail, Outlook's create_draft doesn't take a thread_id —
# thread reply support for Outlook is deferred to Week 5.

def outlook_create_draft(to_email: str, subject: str, body: str) -> str:
    try:
        result = create_draft(
            to_email=to_email,
            subject=subject,
            body=body
        )

        # result from connector:
        # {"status": "draft_saved", "label": "Draft saved",
        #  "to": ..., "subject": ..., "preview": ...}
        return _serialise(result)

    except Exception as e:
        return _serialise({"error": f"outlook_create_draft failed: {str(e)}"})


# ── outlook_send_message ──────────────────────────────────────────────────────
# Wraps: send_message() from outlook_connector.py
#
# Like gmail_send_message — this tool trusts the agent to have confirmed
# with the user before calling (MG-14). Enforcement is in the agent loop.
# This function just fires the send and returns a status dict.

def outlook_send_message(to_email: str, subject: str, body: str) -> str:
    try:
        result = send_message(
            to_email=to_email,
            subject=subject,
            body=body
        )

        # result from connector:
        # {"status": "sent", "to": ..., "subject": ...}
        return _serialise(result)

    except Exception as e:
        return _serialise({"error": f"outlook_send_message failed: {str(e)}"})