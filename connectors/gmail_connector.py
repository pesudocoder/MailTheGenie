# connectors/gmail_connector.py
#
# Week 1:  get_gmail_service, get_recent_emails (basic auth + email fetch)
# Week 3:  create_draft, send_message, get_threads (draft + send + threads)
# Week 6:  _extract_body, get_thread_messages, _user_has_replied,
#          _is_older_than, _is_automated_sender, detect_unresponded_emails,
#          display_unresponded_table, send_draft
#          + get_recent_emails updated: format="full", internalDate, body, sender

import os
import base64
import time
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# ── OAuth scopes ───────────────────────────────────────────────────────────────
# If you add or remove a scope, delete .tokens/gmail_token.json and
# re-run — Gmail will ask for consent again with the updated permissions.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",  # read messages + threads
    "https://www.googleapis.com/auth/gmail.compose",   # create drafts
    "https://www.googleapis.com/auth/gmail.send",      # send emails / drafts
]

TOKEN_PATH       = ".tokens/gmail_token.json"
CREDENTIALS_PATH = "credentials.json"

# ── Week 6 config ──────────────────────────────────────────────────────────────
# Read from .env so you can change these without touching code.
# UNRESPONDED_THRESHOLD_HOURS=48 means: only flag emails older than 48 hours.
THRESHOLD_HOURS = int(os.getenv("UNRESPONDED_THRESHOLD_HOURS", 48))

# These sender-string patterns identify automated / system emails.
# Any email whose From field contains one of these strings is skipped
# during unresponded detection — we never expect a human reply to them.
AUTOMATED_PATTERNS = [
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "newsletter", "notifications", "mailer", "updates",
    "digest", "support@", "info@", "alerts@",
]


# ════════════════════════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════════════════════════

def get_gmail_service():
    """
    Authenticate with Gmail via OAuth 2.0 and return an authorised service.

    Flow:
    1. If .tokens/gmail_token.json exists, load it.
    2. If the token is expired but has a refresh_token, silently refresh it.
    3. If there is no valid token at all, open the browser OAuth flow.
    4. Save the (possibly new) token back to disk for next time.

    The returned `service` object is what every other function in this
    file passes as its first argument.
    """
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Persist the token so the next run doesn't need the browser
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ════════════════════════════════════════════════════════════════════════════════
# READ
# ════════════════════════════════════════════════════════════════════════════════

def get_recent_emails(service, max_results: int = 50) -> list:
    """
    Return a list of recent emails from the inbox.

    WEEK 6 CHANGE — format changed from "metadata" to "full".
    Why: format="metadata" does NOT return internalDate or the message body.
    internalDate is the Unix timestamp (milliseconds) we need to calculate
    how old an email is for unresponded detection.
    format="full" returns headers + body + internalDate in one API call.

    Each returned dict has these keys:
        id           — Gmail message ID (internal, used for API calls)
        thread_id    — thread this message belongs to (used for reply threading)
        subject      — email subject line
        sender       — display name + address, e.g. "Ravi <ravi@client.com>"
        from         — same as sender (alias — some callers use "from")
        received_at  — Python datetime object (timezone-aware)
        internalDate — raw Unix timestamp in milliseconds (used by age check)
        body         — first 500 chars of plain-text body (for LLM triage)
        is_read      — True if UNREAD label is absent
    """
    result = service.users().messages().list(
        userId="me",
        maxResults=max_results
    ).execute()

    messages = result.get("messages", [])
    emails   = []

    for msg in messages:
        # format="full" — returns payload (headers + body parts) + internalDate
        # This is heavier than "metadata" but gives us everything we need
        # in a single API call per message instead of two.
        msg_data = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="full"          # ← WEEK 6 CHANGE (was "metadata")
        ).execute()

        headers  = msg_data["payload"]["headers"]
        subject  = next(
            (h["value"] for h in headers if h["name"] == "Subject"),
            "(no subject)"
        )
        sender   = next(
            (h["value"] for h in headers if h["name"] == "From"),
            "Unknown"
        )
        date_str = next(
            (h["value"] for h in headers if h["name"] == "Date"),
            ""
        )

        # Parse the RFC 2822 date string into a timezone-aware datetime object.
        # Fall back to "now" if parsing fails (malformed header).
        try:
            received_at = parsedate_to_datetime(date_str)
        except Exception:
            received_at = datetime.now(timezone.utc)

        # internalDate: Gmail-internal Unix timestamp in milliseconds.
        # WEEK 6 ADDITION — needed by _is_older_than() for age calculation.
        internal_date_ms = int(msg_data.get("internalDate", 0))

        emails.append({
            "id":            msg["id"],
            "thread_id":     msg_data.get("threadId", ""),
            "subject":       subject,
            "sender":        sender,          # WEEK 6 ADDITION — triage_agent uses "sender"
            "from":          sender,          # kept for backward compatibility
            "received_at":   received_at,
            "internalDate":  internal_date_ms, # WEEK 6 ADDITION — milliseconds
            "body":          _extract_body(msg_data)[:500],  # WEEK 6 ADDITION
            "is_read":       "UNREAD" not in msg_data.get("labelIds", []),
        })

    return emails


def get_threads(service, max_results: int = 10, query: str = "") -> list:
    """
    Fetch a list of Gmail threads (conversations), not individual messages.

    A thread groups all replies to the same email chain under one threadId.
    Useful for queries like "show me the conversation with Ravi".

    query accepts Gmail search syntax, e.g.:
        "from:ravi@client.com"
        "is:unread"
        "subject:contract"

    Returns thread_id + snippet (short preview of the latest message).
    thread_id is internal — the agent uses it for reply threading, never
    shown to the user.
    """
    params = {"userId": "me", "maxResults": max_results}
    if query:
        params["q"] = query

    result  = service.users().threads().list(**params).execute()
    threads = result.get("threads", [])

    return [
        {
            "thread_id": t["id"],
            "snippet":   t.get("snippet", "")
        }
        for t in threads
    ]


# ════════════════════════════════════════════════════════════════════════════════
# DRAFT + SEND
# ════════════════════════════════════════════════════════════════════════════════

def create_draft(
    service,
    to_email: str,
    subject: str,
    body: str,
    thread_id: str = None
) -> dict:
    """
    Create a Gmail draft without sending it.

    Steps:
    1. Build an RFC 2822 email object using Python's MIMEText.
    2. base64url-encode the raw bytes — this is what Gmail API requires
       in the "raw" field. Plain JSON text is NOT accepted.
    3. POST to drafts.create — Gmail stores it in Drafts folder.

    thread_id (optional): if provided, the draft is attached to that
    conversation thread, so when sent it appears as a reply.

    WEEK 6 CHANGE — added "_draft_id" to the return dict.
    The agent needs the draft ID internally to call send_draft() later.
    It is prefixed with "_" as a convention meaning "internal only —
    do not display to the user" (satisfies MG-03).
    """
    message            = MIMEText(body)
    message["to"]      = to_email
    message["subject"] = subject

    raw_bytes  = base64.urlsafe_b64encode(message.as_bytes())
    raw_string = raw_bytes.decode("utf-8")

    draft_body = {"message": {"raw": raw_string}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    result = service.users().drafts().create(
        userId="me",
        body=draft_body
    ).execute()

    return {
        "status":    "draft_saved",
        "label":     "Draft saved",
        "to":        to_email,
        "subject":   subject,
        "preview":   body[:200],
        "_draft_id": result["id"],   # WEEK 6 ADDITION — internal use only
    }


def send_draft(service, draft_id: str) -> dict:
    """
    WEEK 6 ADDITION — Send a previously saved draft by its internal ID.

    This is the second half of the MG-14 two-step send flow:
      Step 1: create_draft() → agent shows preview, stores _draft_id in state
      Step 2: send_draft()   → called ONLY after user types "confirm send"

    Why separate from send_message()?
    send_message() constructs a brand new email each time.
    send_draft() fires the exact draft the user already reviewed —
    no risk of the content changing between preview and send.

    The draft_id comes from state["pending_draft_id"] in the agent,
    which was set from create_draft()'s "_draft_id" return value.
    The agent never shows this ID to the user.
    """
    result = service.users().drafts().send(
        userId="me",
        body={"id": draft_id}
    ).execute()

    return {
        "status":     "sent",
        "message_id": result.get("id", "")
    }


def send_message(
    service,
    to_email: str,
    subject: str,
    body: str,
    thread_id: str = None
) -> dict:
    """
    Send an email immediately (no draft step).

    Used for composing new emails (MG-16), not for draft replies.
    For draft replies, use create_draft() + send_draft() instead.

    In the agent this is ONLY called after explicit user confirmation (MG-14).
    thread_id is optional — attaches the sent email to an existing thread.
    """
    message            = MIMEText(body)
    message["to"]      = to_email
    message["subject"] = subject

    raw_bytes  = base64.urlsafe_b64encode(message.as_bytes())
    raw_string = raw_bytes.decode("utf-8")

    send_body = {"raw": raw_string}
    if thread_id:
        send_body["threadId"] = thread_id

    service.users().messages().send(
        userId="me",
        body=send_body
    ).execute()

    return {"status": "sent", "to": to_email, "subject": subject}


# ════════════════════════════════════════════════════════════════════════════════
# WEEK 6 — UNRESPONDED EMAIL DETECTION (MG-08)
# ════════════════════════════════════════════════════════════════════════════════

def get_thread_messages(service, thread_id: str) -> list:
    """
    Fetch every message object in a Gmail thread.

    We need all messages in the thread — not just the first one —
    because the user's reply could be message 2, 3, or 4 in the chain.
    We check ALL of them for the SENT label.

    format="metadata" is enough here because we only need labelIds
    (to check for SENT) and a couple of headers (From, Date).
    Using "full" here would be wasteful — we don't need the body.

    Returns a list of message objects, each with:
        labelIds  — e.g. ["INBOX", "UNREAD"] or ["SENT"]
        payload   — headers (From, Date)
    """
    thread_data = service.users().threads().get(
        userId="me",
        id=thread_id,
        format="metadata",
        metadataHeaders=["From", "Date"]
    ).execute()

    return thread_data.get("messages", [])


def _user_has_replied(thread_messages: list) -> bool:
    """
    Return True if any message in the thread carries the "SENT" label.

    Why check SENT label instead of matching the From header?

    The SENT label is set by Gmail on every outgoing message regardless
    of which email address or alias you sent from. If your Gmail account
    is you@gmail.com but you also send as alias@company.com, both outgoing
    messages get the SENT label. Matching the From header would require
    knowing all your aliases — fragile and unnecessary.

    Checking labelIds["SENT"] is one line and always correct.
    """
    for msg in thread_messages:
        if "SENT" in msg.get("labelIds", []):
            return True
    return False


def _is_older_than(internal_date_ms: int, threshold_hours: int) -> bool:
    """
    Return True if the email is older than threshold_hours.

    internalDate from Gmail is milliseconds since epoch.
    time.time() returns seconds since epoch.
    So we divide internalDate by 1000 before subtracting.

    Example:
        internalDate = 1_700_000_000_000 ms
        time.time()  = 1_700_180_000    seconds
        age_seconds  = 1_700_180_000 - 1_700_000_000 = 180_000 seconds
        age_hours    = 180_000 / 3600 = 50 hours
        50 > 48 → True → flag this email
    """
    age_seconds = time.time() - (internal_date_ms / 1000)
    age_hours   = age_seconds / 3600
    return age_hours > threshold_hours


def _is_automated_sender(sender: str) -> bool:
    """
    Return True if the sender string looks like an automated system.

    We check the full sender string — which includes both the display
    name and the email address, e.g. "GitHub <noreply@github.com>" —
    so both "noreply" in the name and "noreply@" in the address are caught.

    This pre-filter runs BEFORE the thread fetch, so we avoid an API
    call for every newsletter or system notification in the inbox.
    """
    sender_lower = sender.lower()
    return any(pattern in sender_lower for pattern in AUTOMATED_PATTERNS)


def detect_unresponded_emails(
    service,
    emails: list,
    threshold_hours: int = THRESHOLD_HOURS
) -> list:
    """
    MG-08: Find emails where the user has NOT replied within threshold_hours.

    Algorithm (runs for each email in the list):

        Step 1 — Guard: does this email have internalDate?
                 (Only emails fetched with format="full" will have it.
                  Skip safely if it's missing.)

        Step 2 — Pre-filter: is the sender automated?
                 (Newsletters, noreply, alerts → skip immediately.
                  No API call needed.)

        Step 3 — Age check: is the email older than threshold_hours?
                 (Too recent → skip. User may still be planning to reply.)

        Step 4 — Thread fetch: get every message in the thread.
                 (One API call per email that passes steps 1-3.)

        Step 5 — SENT check: did any message in the thread get sent by user?
                 (Yes → skip. No → flag as unresponded.)

    Returns a list of dicts:
        sender, subject, received_at, days_waiting, thread_id, id
    """
    
    unresponded = []

    for email in emails:

        # Step 1: guard — internalDate must be present and non-zero
        if not email.get("internalDate"):
            continue

        # Step 2: skip automated senders — no thread API call needed
        sender = email.get("sender") or email.get("from", "")
        if _is_automated_sender(sender):
            continue

        # Step 3: skip emails that are too recent
        if not _is_older_than(email["internalDate"], threshold_hours):
            continue

        # Step 4: fetch the full thread — one API call per email
        thread_msgs = get_thread_messages(service, email["thread_id"])

        # Step 5: if the user replied anywhere in the thread, skip
        if _user_has_replied(thread_msgs):
            continue

        # Passed all checks — calculate how many days it has been waiting
        age_seconds  = time.time() - (email["internalDate"] / 1000)
        days_waiting = round(age_seconds / 86400, 1)  # 86400 seconds per day

        unresponded.append({
            "sender":       sender,
            "subject":      email["subject"],
            "received_at":  str(email["received_at"]),
            "days_waiting": days_waiting,
            "thread_id":    email["thread_id"],
            "id":           email["id"],
        })

    return unresponded


def display_unresponded_table(unresponded: list):
    """
    Print unresponded emails in MG-10 table format.
    Output: Sender | Subject | Days Waiting
    """
    if not unresponded:
        print("  No unresponded emails found.")
        return

    print("\n" + "=" * 75)
    print(f"  {'Sender':<26} {'Subject':<28} Days Waiting")
    print("=" * 75)

    for e in unresponded:
        sender  = e["sender"][:25]
        subject = e["subject"][:27]
        days    = e["days_waiting"]
        print(f"  {sender:<26} {subject:<28} {days} days")

    print("=" * 75 + "\n")


# ════════════════════════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ════════════════════════════════════════════════════════════════════════════════

def _extract_body(msg_data: dict) -> str:
    """
    WEEK 6 ADDITION — Walk the Gmail payload tree to find the plain text body.

    Gmail structures emails as a tree of MIME parts:

        Simple email (text/plain):
            payload
            └── body.data   ← base64url-encoded text

        Multipart email (text/plain + text/html):
            payload
            └── parts
                ├── [0] mimeType="text/plain"  ← we want this one
                │       body.data
                └── [1] mimeType="text/html"

    We always prefer text/plain — it's simpler for the LLM to read and
    doesn't include HTML tags that waste context window tokens.

    All body data from Gmail is base64url-encoded bytes.
    base64.urlsafe_b64decode() converts it back to bytes.
    .decode("utf-8", errors="replace") converts bytes to a Python string.
    errors="replace" prevents crashes on emails with non-UTF-8 characters.
    """
    payload = msg_data.get("payload", {})

    # Case 1: simple non-multipart email — body is directly on the payload
    body_data = payload.get("body", {}).get("data", "")
    if body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

    # Case 2: multipart email — scan the parts list for text/plain
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Case 3: no body found (e.g. empty email or unsupported format)
    return ""


# ════════════════════════════════════════════════════════════════════════════════
# ENTRY POINT — quick sanity check
# ════════════════════════════════════════════════════════════════════════════════

def main():
    """
    Run from MAILTHEGENIE/ root:
        python -m connectors.gmail_connector

    Connects to Gmail, fetches 10 recent emails, and prints them.
    Use this to verify auth is working after adding new OAuth scopes.
    """
    print("Connecting to Gmail...")
    service = get_gmail_service()
    print("Connected!\n")

    emails = get_recent_emails(service, max_results=10)

    print("Recent Emails")
    print("-" * 50)
    for i, email in enumerate(emails, 1):
        read_flag = "" if email["is_read"] else " [UNREAD]"
        print(f"{i:2}. {email['subject']}{read_flag}")
        print(f"    From: {email['from']}")
        print(f"    Date: {email['received_at']}")
        print(f"    Body: {email['body'][:80]}...")
        print()


if __name__ == "__main__":
    main()