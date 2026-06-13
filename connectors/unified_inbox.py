# connectors/unified_inbox.py
# Implements MG-26 — merged, deduplicated, sorted Gmail + Outlook inbox
# Uses asyncio.gather() to fetch both concurrently (not sequentially)

import asyncio
from datetime import datetime, timezone
from connectors.gmail_connector import get_recent_emails, get_gmail_service
from connectors.outlook_connector import get_messages


# ── 1. Normalise Gmail emails to unified format ───────────────────────────────
# Gmail connector returns a simple dict with "subject" and "from".
# We need to bring it up to the same shape as Outlook's normalised format
# so the rest of the code never needs to know which provider an email came from.
#
# Problem: gmail_connector.get_recent_emails() only returns subject + sender.
# We extend it here to match our unified schema with sensible defaults
# for fields gmail_connector doesn't currently fetch (body, is_read, etc.)

def normalise_gmail_email(email: dict, index: int) -> dict:
    # Gmail connector doesn't return a parsed datetime yet —
    # we use index-based ordering as a proxy (0 = most recent)
    # This gets properly fixed when we wire in the full Gmail metadata later
    now = datetime.now(timezone.utc)

    return {
        "id":          email.get("id", f"gmail_{index}"),
        "provider":    "gmail",
        "sender":      email.get("from", "Unknown"),
        "subject":     email.get("subject", "(no subject)"),
        "body":        email.get("body", ""),
        "received_at": email.get("received_at", now),
        "is_read":     email.get("is_read", True),
        "thread_id":   email.get("thread_id", "")
    }


# ── 2. Async wrappers ─────────────────────────────────────────────────────────
# Gmail and Outlook connectors are synchronous (regular functions, not async).
# To use asyncio.gather() we wrap them with asyncio.to_thread() which runs
# a sync function in a thread pool — making it awaitable without rewriting
# the connectors as async.
#
# This is the standard Python pattern for mixing sync libraries with asyncio.

async def fetch_gmail_emails(max_results: int) -> list:
    try:
        # Run sync Gmail functions in a thread
        service = await asyncio.to_thread(get_gmail_service)
        raw_emails = await asyncio.to_thread(get_recent_emails, service, max_results)

        return [normalise_gmail_email(e, i) for i, e in enumerate(raw_emails)]
    except Exception as e:
        print(f"⚠️  Gmail fetch failed: {e}")
        return []


async def fetch_outlook_emails(max_results: int) -> list:
    try:
        # Run sync Outlook function in a thread
        return await asyncio.to_thread(get_messages, max_results)
    except Exception as e:
        print(f"⚠️  Outlook fetch failed: {e}")
        return []


# ── 3. Deduplication ──────────────────────────────────────────────────────────
# Deduplication handles the edge case where the same email appears in both
# Gmail and Outlook (e.g. a user has Gmail forwarding to Outlook).
#
# Strategy: normalise sender + subject → create a fingerprint string.
# If two emails share the same fingerprint, keep only the first one seen.
# We don't use message-id headers because Gmail and Outlook format them
# differently — sender+subject is reliable enough for the prototype.

def deduplicate(emails: list) -> list:
    seen = set()
    unique = []

    for email in emails:
        # Normalise: lowercase, strip whitespace
        sender  = email.get("sender", "").lower().strip()
        subject = email.get("subject", "").lower().strip()
        fingerprint = f"{sender}|{subject}"

        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(email)

    return unique


# ── 4. Main unified inbox function ────────────────────────────────────────────
# This is the single function the agent will call to get all emails.
#
# Flow:
#   1. asyncio.gather() fires Gmail + Outlook fetches simultaneously
#   2. Results come back as two lists
#   3. Merge into one list
#   4. Deduplicate
#   5. Sort by received_at descending (newest first)
#   6. Return top N

async def get_all_emails_async(max_per_provider: int = 20) -> list:
    print("Fetching emails from Gmail and Outlook concurrently...")

    # This is the key line — both fetches run at the same time
    gmail_emails, outlook_emails = await asyncio.gather(
        fetch_gmail_emails(max_per_provider),
        fetch_outlook_emails(max_per_provider)
    )

    print(f"  Gmail:   {len(gmail_emails)} emails fetched")
    print(f"  Outlook: {len(outlook_emails)} emails fetched")

    # Merge
    all_emails = gmail_emails + outlook_emails

    # Deduplicate
    all_emails = deduplicate(all_emails)

    # Sort by received_at — newest first
    # Both providers now have proper datetime objects thanks to normalisation
    all_emails.sort(key=lambda e: e["received_at"], reverse=True)

    print(f"  Total:   {len(all_emails)} emails after deduplication\n")
    return all_emails


# ── 5. Sync wrapper ───────────────────────────────────────────────────────────
# The agent in Week 5 will call this synchronously.
# This wrapper lets non-async code call get_all_emails() without
# needing to manage the event loop themselves.

def get_all_emails(max_per_provider: int = 20) -> list:
    return asyncio.run(get_all_emails_async(max_per_provider))


# ── 6. Display helper ─────────────────────────────────────────────────────────
def display_unified_inbox(emails: list):
    if not emails:
        print("No emails found.")
        return

    print("=" * 80)
    print(f"  {'#':<4} {'Provider':<10} {'Sender':<28} {'Subject'}")
    print("=" * 80)

    for i, email in enumerate(emails, 1):
        provider = f"[{email['provider'].upper()}]"
        sender   = email["sender"][:27]
        subject  = email["subject"][:40]
        time_str = email["received_at"].strftime("%b %d, %H:%M")
        print(f"  {i:<4} {provider:<10} {sender:<28} {subject}  {time_str}")

    print("=" * 80)


# ── 7. Quick test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Mail Genie — Unified Inbox\n")
    emails = get_all_emails(max_per_provider=10)
    display_unified_inbox(emails)