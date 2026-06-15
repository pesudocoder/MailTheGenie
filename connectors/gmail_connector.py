import os
import base64
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# The scopes we're requesting from Google
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",   # create drafts
    "https://www.googleapis.com/auth/gmail.send",      # send emails
]
TOKEN_PATH = ".tokens/gmail_token.json"
CREDENTIALS_PATH = "credentials.json"


def get_gmail_service():
    creds = None

    # If token.json exists, load saved credentials
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If no valid credentials, do the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Silently refresh the access token
            creds.refresh(Request())
        else:
            # First time — open browser for user to log in
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save tokens for next time
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_recent_emails(service, max_results=10):
    result = service.users().messages().list(
        userId="me",
        maxResults=max_results
    ).execute()

    messages = result.get("messages", [])
    emails = []

    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()

        headers   = msg_data["payload"]["headers"]
        subject   = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
        sender    = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
        date_str  = next((h["value"] for h in headers if h["name"] == "Date"), "")

        # Parse Gmail date string into datetime
        from email.utils import parsedate_to_datetime
        try:
            received_at = parsedate_to_datetime(date_str)
        except Exception:
            from datetime import datetime, timezone
            received_at = datetime.now(timezone.utc)

        emails.append({
            "id":          msg["id"],
            "subject":     subject,
            "from":        sender,
            "received_at": received_at,
            "is_read":     "UNREAD" not in msg_data.get("labelIds", []),
            "thread_id":   msg_data.get("threadId", "")
        })

    return emails



# ── create_draft() ────────────────────────────────────────────────────────────
# Creates a draft in Gmail without sending it.
# Gmail API requires the email to be base64url-encoded — not plain JSON like Outlook.
#
# MIMEText builds a proper RFC-2822 email object.
# base64.urlsafe_b64encode() converts it to bytes Gmail accepts.
# decode("utf-8") turns those bytes back to a string for the API call.
#
# thread_id is optional — if provided, the draft is a reply in that thread.
# Returns a friendly dict (never the raw Gmail draft ID — satisfies MG-03).

def create_draft(service, to_email: str, subject: str, body: str, thread_id: str = None) -> dict:
    # Build a MIME email object
    message = MIMEText(body)
    message["to"]      = to_email
    message["subject"] = subject

    # Encode to base64url — this is what Gmail API expects in the "raw" field
    raw_bytes   = base64.urlsafe_b64encode(message.as_bytes())
    raw_string  = raw_bytes.decode("utf-8")

    # Build the request body
    draft_body = {"message": {"raw": raw_string}}

    # If replying to a thread, attach the thread ID
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    # Call Gmail API — creates draft, returns draft object with an ID
    result = service.users().drafts().create(
        userId="me",
        body=draft_body
    ).execute()

    # Return user-friendly response — hide the internal draft ID (MG-03)
    return {
        "status":  "draft_saved",
        "label":   "Draft saved",
        "to":      to_email,
        "subject": subject,
        "preview": body[:200]
    }


# ── send_message() ────────────────────────────────────────────────────────────
# Sends an email immediately.
# Uses the same base64url encoding as create_draft().
# In the agent this is ONLY called after explicit user confirmation (MG-14).
#
# thread_id is optional — attaches the sent email to an existing thread.

def send_message(service, to_email: str, subject: str, body: str, thread_id: str = None) -> dict:
    message = MIMEText(body)
    message["to"]      = to_email
    message["subject"] = subject

    raw_bytes  = base64.urlsafe_b64encode(message.as_bytes())
    raw_string = raw_bytes.decode("utf-8")

    send_body = {"raw": raw_string}

    # Attach to thread if replying
    if thread_id:
        send_body["threadId"] = thread_id

    # gmail.users().messages().send() — fires immediately, no draft
    service.users().messages().send(
        userId="me",
        body=send_body
    ).execute()

    return {
        "status":  "sent",
        "to":      to_email,
        "subject": subject
    }


# ── get_threads() ─────────────────────────────────────────────────────────────
# Fetches email threads instead of individual messages.
# A thread groups all replies to the same email chain.
# Useful for "show me the conversation with Ravi" queries.
#
# Returns thread ID + snippet (first ~100 chars of the latest message).
# The agent uses thread IDs internally to reply in-thread — never shown to user.

def get_threads(service, max_results: int = 10, query: str = "") -> list:
    # List threads — optionally filtered by a Gmail search query
    # e.g. query="from:ravi@client.com" or query="is:unread"
    params = {
        "userId":     "me",
        "maxResults": max_results,
    }
    if query:
        params["q"] = query   # Gmail search syntax

    result = service.users().threads().list(**params).execute()
    threads = result.get("threads", [])

    # Each thread in the list only has id + snippet
    # snippet = short preview of the most recent message in the thread
    return [
        {
            "thread_id": t["id"],        # internal — agent uses this, never shown to user
            "snippet":   t.get("snippet", "")
        }
        for t in threads
    ]


def main():
    print("Connecting to Gmail...")
    service = get_gmail_service()
    print("Connected!\n")

    emails = get_recent_emails(service)

    print("Recent Emails")
    print("-" * 40)
    for i, email in enumerate(emails, 1):
        print(f"{i:2}. {email['subject']}")
        print(f"    From: {email['from']}\n")


if __name__ == "__main__":
    main()