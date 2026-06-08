import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# The scopes we're requesting from Google
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    creds = None

    # If token.json exists, load saved credentials
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # If no valid credentials, do the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Silently refresh the access token
            creds.refresh(Request())
        else:
            # First time — open browser for user to log in
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        # Save tokens for next time
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_recent_emails(service, max_results=10):
    # Step 1 — get list of message IDs
    result = service.users().messages().list(
        userId="me",
        maxResults=max_results
    ).execute()

    messages = result.get("messages", [])

    # Step 2 — fetch subject for each message
    emails = []
    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["Subject", "From"]
        ).execute()

        headers = msg_data["payload"]["headers"]
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
        sender  = next((h["value"] for h in headers if h["name"] == "From"), "(unknown)")
        emails.append({"subject": subject, "from": sender})

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