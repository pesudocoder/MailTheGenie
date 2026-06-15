# mcp_tools/gmail_tools.py
# Gmail tool implementations — the actual Python functions that run
# when the LLM calls a Gmail tool by name.
#
# Each function here maps 1-to-1 with a definition in definitions.py.
# The executor.py will call these functions by name.
#
# Design rule: every function takes only simple types (str, int) as arguments
# — exactly what the LLM passes in tool_call arguments.
# The service object is created inside each function, not passed in.
# This keeps the executor simple — it just unpacks **kwargs and calls the function.


import json
from connectors.gmail_connector import (
    get_gmail_service,   # returns authenticated Gmail API service object
    get_recent_emails,   # fetches emails — returns list of dicts
    create_draft,        # creates draft — returns friendly status dict
    send_message,        # sends email — returns friendly status dict
    get_threads,         # fetches threads — returns list of dicts
)


# ── Helper: serialise datetime objects ────────────────────────────────────────
# json.dumps() crashes on datetime objects — they're not JSON serialisable.
# This helper converts any datetime to an ISO string before serialising.
# We use this on every tool result before returning it to the executor.
# The executor passes the result string back to the LLM as the tool message.

def _serialise(data) -> str:
    # default=str converts any non-serialisable object (datetime, etc.) to string
    return json.dumps(data, default=str, ensure_ascii=False)


# ── gmail_get_messages ────────────────────────────────────────────────────────
# Wraps: get_gmail_service() + get_recent_emails()
#
# Why does the service get created inside here?
# Because each tool call is stateless — we don't hold a persistent service
# object across calls. get_gmail_service() is cheap (reads token from file,
# refreshes silently if needed) so creating it per-call is fine.
#
# The query parameter maps to Gmail's search syntax.
# get_recent_emails() doesn't support query yet — we pass it through
# via the service.users().messages().list() call directly here
# so we don't have to modify the connector.

def gmail_get_messages(max_results: int = 10, query: str = "") -> str:
    try:
        service = get_gmail_service()

        # If no query, use the connector's standard function
        if not query:
            emails = get_recent_emails(service, max_results=max_results)

        else:
            # Query path: call the Gmail API directly with a search filter
            # This mirrors what get_recent_emails() does internally,
            # but adds the q= parameter for filtering
            result = service.users().messages().list(
                userId="me",
                maxResults=max_results,
                q=query           # Gmail search syntax: "is:unread", "from:ravi@..."
            ).execute()

            raw_messages = result.get("messages", [])
            emails = []

            for msg in raw_messages:
                msg_data = service.users().messages().get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"]
                ).execute()

                headers = msg_data["payload"]["headers"]

                subject  = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
                sender   = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
                date_str = next((h["value"] for h in headers if h["name"] == "Date"), "")

                from email.utils import parsedate_to_datetime
                from datetime import datetime, timezone
                try:
                    received_at = parsedate_to_datetime(date_str)
                except Exception:
                    received_at = datetime.now(timezone.utc)

                emails.append({
                    "id":          msg["id"],
                    "subject":     subject,
                    "sender":      sender,        # note: unified key is "sender" not "from"
                    "received_at": received_at,
                    "is_read":     "UNREAD" not in msg_data.get("labelIds", []),
                    "thread_id":   msg_data.get("threadId", "")
                })

        # Strip internal message IDs from what the LLM sees (MG-03)
        # We keep thread_id because it's needed for reply drafts,
        # but we label it clearly so the LLM knows it's a reference handle
        safe_emails = []
        for e in emails:
            safe_emails.append({
                "sender":      e.get("from", e.get("sender", "Unknown")),
                "subject":     e.get("subject", "(no subject)"),
                "received_at": e.get("received_at", ""),
                "is_read":     e.get("is_read", True),
                "thread_id":   e.get("thread_id", ""),  # kept for reply use
                "provider":    "gmail"
            })

        return _serialise({
            "provider": "gmail",
            "count":    len(safe_emails),
            "emails":   safe_emails
        })

    except Exception as e:
        # Always return a string — never raise from a tool function.
        # The executor catches errors but a string error is cleaner for the LLM.
        return _serialise({"error": f"gmail_get_messages failed: {str(e)}"})


# ── gmail_create_draft ────────────────────────────────────────────────────────
# Wraps: create_draft() from gmail_connector.py
#
# thread_id defaults to "" — the connector treats "" the same as None
# (no thread attachment). We normalise it here so the connector
# receives either a real ID or None, never an empty string.

def gmail_create_draft(to_email: str, subject: str, body: str, thread_id: str = "") -> str:
    try:
        service = get_gmail_service()

        # Convert empty string to None — connector checks `if thread_id:`
        thread_id_or_none = thread_id if thread_id else None

        result = create_draft(
            service=service,
            to_email=to_email,
            subject=subject,
            body=body,
            thread_id=thread_id_or_none
        )

        # result is already a friendly dict from the connector (MG-03 compliant)
        # e.g. {"status": "draft_saved", "label": "Draft saved", "to": ..., "preview": ...}
        return _serialise(result)

    except Exception as e:
        return _serialise({"error": f"gmail_create_draft failed: {str(e)}"})


# ── gmail_send_message ────────────────────────────────────────────────────────
# Wraps: send_message() from gmail_connector.py
#
# This tool should only be called after user confirmation (MG-14).
# That enforcement lives in the agent loop (Week 5), not here.
# The tool itself just fires — it trusts the agent to have confirmed first.

def gmail_send_message(to_email: str, subject: str, body: str, thread_id: str = "") -> str:
    try:
        service = get_gmail_service()

        thread_id_or_none = thread_id if thread_id else None

        result = send_message(
            service=service,
            to_email=to_email,
            subject=subject,
            body=body,
            thread_id=thread_id_or_none
        )

        # result: {"status": "sent", "to": ..., "subject": ...}
        return _serialise(result)

    except Exception as e:
        return _serialise({"error": f"gmail_send_message failed: {str(e)}"})


# ── gmail_get_threads ─────────────────────────────────────────────────────────
# Wraps: get_threads() from gmail_connector.py
#
# Returns thread_id + snippet for each thread.
# thread_id is included because the agent needs it to draft replies —
# but it's never displayed to the user directly.

def gmail_get_threads(max_results: int = 10, query: str = "") -> str:
    try:
        service = get_gmail_service()

        threads = get_threads(
            service=service,
            max_results=max_results,
            query=query
        )

        # threads: [{"thread_id": "...", "snippet": "..."}]
        # thread_id stays in — agent needs it, but LLM response to user won't show it
        return _serialise({
            "provider": "gmail",
            "count":    len(threads),
            "threads":  threads
        })

    except Exception as e:
        return _serialise({"error": f"gmail_get_threads failed: {str(e)}"})