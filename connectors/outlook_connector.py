# connectors/outlook_connector.py
# Implements Outlook OAuth via MSAL + Microsoft Graph API
# Covers: get_messages(), create_draft(), send_message()

import os
import json
import msal
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── 1. Azure App Config ───────────────────────────────────────────────────────
CLIENT_ID     = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
TENANT_ID     = os.getenv("AZURE_TENANT_ID")

AUTHORITY     = f"https://login.microsoftonline.com/common"
GRAPH_BASE    = "https://graph.microsoft.com/v1.0"

SCOPES = [
    "Mail.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    "User.Read"
]

# Where we cache the token so we don't re-login every run
TOKEN_CACHE_PATH = ".tokens/outlook_token.json"


# ── 2. Token Cache Setup ──────────────────────────────────────────────────────
# MSAL has a built-in token cache system.
# SerializableTokenCache lets us save it to a file (like token.json in Gmail).
# On startup we load the cache → MSAL finds the saved token → no browser popup.
# On exit we save the cache → tokens persist for next run.

def load_token_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_PATH):
        with open(TOKEN_CACHE_PATH, "r") as f:
            cache.deserialize(f.read())
    return cache


def save_token_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        os.makedirs(".tokens", exist_ok=True)
        with open(TOKEN_CACHE_PATH, "w") as f:
            f.write(cache.serialize())


# ── 3. Get Access Token ───────────────────────────────────────────────────────
# This is the core auth function — equivalent to get_gmail_service() in Gmail.
#
# Flow:
#   1. Load cache from file
#   2. Try silent token (uses refresh token under the hood — no browser)
#   3. If silent fails (first run / token expired) → open browser for login
#   4. Save cache back to file
#
# Returns: access token string (used in Authorization header for all API calls)

def get_access_token() -> str:
    cache = load_token_cache()

    # Build the MSAL app — PublicClientApplication = desktop/CLI app
    # (vs ConfidentialClientApplication which is for server-side apps)
    app = msal.PublicClientApplication(
        client_id=CLIENT_ID,
        authority=AUTHORITY,
        token_cache=cache
    )

    token_result = None

    # Step 1 — check if we have a cached account
    accounts = app.get_accounts()
    if accounts:
        # acquire_token_silent uses the refresh token to get a new access token
        # completely silent — no browser, no user interaction
        token_result = app.acquire_token_silent(SCOPES, account=accounts[0])

    # Step 2 — no cache or silent refresh failed → open browser
    if not token_result:
        print("No cached token found. Opening browser for Outlook login...")
        token_result = app.acquire_token_interactive(scopes=SCOPES)

    # Save updated cache (new access token / refresh token) to file
    save_token_cache(cache)

    if "access_token" not in token_result:
        error = token_result.get("error_description", "Unknown error")
        raise Exception(f"Outlook authentication failed: {error}")

    print("Outlook authenticated successfully.")
    return token_result["access_token"]


# ── 4. Graph API Helper ───────────────────────────────────────────────────────
# All Microsoft Graph calls follow the same pattern:
#   - Base URL: https://graph.microsoft.com/v1.0
#   - Header:   Authorization: Bearer <access_token>
#   - Method:   GET / POST / PATCH
#
# This helper wraps requests so we don't repeat headers everywhere.

def graph_get(endpoint: str, token: str, params: dict = None) -> dict:
    url = f"{GRAPH_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def graph_post(endpoint: str, token: str, body: dict) -> dict:
    url = f"{GRAPH_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers, json=body)
    response.raise_for_status()
    return response.json() if response.content else {}


# ── 5. Normalise Email Format ─────────────────────────────────────────────────
# Gmail and Outlook return emails in completely different shapes.
# We normalise both into the same dict structure so unified_inbox.py
# can treat them identically without caring about the source.
#
# Unified format:
# {
#   "id":          str,
#   "provider":    "outlook",
#   "sender":      str,
#   "subject":     str,
#   "body":        str,
#   "received_at": datetime,   ← always a Python datetime object
#   "is_read":     bool,
#   "thread_id":   str
# }

def normalise_outlook_email(msg: dict) -> dict:
    # Outlook gives us ISO 8601 string: "2026-06-10T09:15:00Z"
    # We parse it into a timezone-aware datetime for sorting
    received_raw = msg.get("receivedDateTime", "")
    try:
        received_dt = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
    except Exception:
        received_dt = datetime.now(timezone.utc)

    return {
        "id":          msg.get("id", ""),
        "provider":    "outlook",
        "sender":      msg.get("from", {}).get("emailAddress", {}).get("address", "Unknown"),
        "subject":     msg.get("subject", "(no subject)"),
        "body":        msg.get("body", {}).get("content", "")[:500],
        "received_at": received_dt,
        "is_read":     msg.get("isRead", False),
        "thread_id":   msg.get("conversationId", "")
    }


# ── 6. get_messages() ─────────────────────────────────────────────────────────
# Fetches latest N emails from Outlook inbox.
# $select — only fetch fields we need (reduces payload size)
# $orderby — newest first
# $top    — number of results (like maxResults in Gmail)

def get_messages(max_results: int = 10) -> list:
    token = get_access_token()

    params = {
        "$select":  "id,subject,from,receivedDateTime,isRead,conversationId,body",
        "$orderby": "receivedDateTime desc",
        "$top":     max_results
    }

    data = graph_get("/me/messages", token, params=params)
    messages = data.get("value", [])

    return [normalise_outlook_email(msg) for msg in messages]


# ── 7. create_draft() ─────────────────────────────────────────────────────────
# Creates a draft email in Outlook (does NOT send it).
# Returns the internal draft ID — this stays hidden from users (MG-03).
#
# to_email: recipient address
# subject:  email subject
# body:     email body text

def create_draft(to_email: str, subject: str, body: str) -> dict:
    token = get_access_token()

    draft_body = {
        "subject": subject,
        "body": {
            "contentType": "Text",
            "content": body
        },
        "toRecipients": [
            {
                "emailAddress": {
                    "address": to_email
                }
            }
        ]
    }

    result = graph_post("/me/messages", token, draft_body)

    # Return a user-friendly response — never expose the raw draft ID (MG-03)
    return {
        "status":  "draft_saved",
        "label":   "Draft saved",
        "to":      to_email,
        "subject": subject,
        "preview": body[:200]
    }


# ── 8. send_message() ─────────────────────────────────────────────────────────
# Sends an email directly (not a draft flow).
# In the agent, this is ONLY called after explicit user confirmation (MG-14).
#
# This uses the /sendMail endpoint which creates and sends in one step.

def send_message(to_email: str, subject: str, body: str) -> dict:
    token = get_access_token()

    mail_body = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": to_email
                    }
                }
            ]
        },
        "saveToSentItems": True
    }

    graph_post("/me/sendMail", token, mail_body)

    return {
        "status":  "sent",
        "to":      to_email,
        "subject": subject
    }


# ── 9. Quick test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Connecting to Outlook...\n")

    emails = get_messages(max_results=10)

    print(f"Recent Outlook Emails")
    print("-" * 50)
    for i, email in enumerate(emails, 1):
        time_str = email["received_at"].strftime("%b %d, %H:%M")
        read_flag = "" if email["is_read"] else "🔵 "
        print(f"{i:2}. {read_flag}{email['subject']}")
        print(f"    From: {email['sender']}  |  {time_str}\n")  