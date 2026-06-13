import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# The scopes we're requesting from Google
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
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