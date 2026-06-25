# scheduler/digest_scheduler.py
#
# MG-18: Autonomous Morning Email Digest
#
# Runs every weekday at 8:00 AM IST with zero manual trigger.
# Uses APScheduler's BackgroundScheduler — fires in a daemon thread
# while the main process stays alive (CLI or future FastAPI app).
#
# Run from MAILTHEGENIE/ root:
#   python -m scheduler.digest_scheduler        ← production (8 AM IST weekdays)
#   python -m scheduler.digest_scheduler dev    ← dev mode (every 30 seconds)

import os
import time
import traceback

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

# ── Import our existing modules from earlier weeks ────────────────────────────
# These are all already built — we are just wiring them together here.
from connectors.gmail_connector import (
    get_gmail_service,
    get_recent_emails,
    detect_unresponded_emails,
    display_unresponded_table,
)
from agents.triage_agent import triage_emails, display_triage_table


# ── Config ────────────────────────────────────────────────────────────────────
# Read from .env so you can change these without touching code.
# Defaults: 8 AM, 0 minutes → 08:00 IST
DIGEST_HOUR   = int(os.getenv("DIGEST_HOUR",   8))
DIGEST_MINUTE = int(os.getenv("DIGEST_MINUTE", 0))

# IST timezone object.
# CRITICAL: always pass this to BackgroundScheduler.
# Without it, APScheduler uses the system timezone — which on a cloud
# server is almost always UTC, meaning 8 AM would fire at 2:30 PM IST.
IST = pytz.timezone("Asia/Kolkata")


# ════════════════════════════════════════════════════════════════════════════════
# THE JOB FUNCTION
# ════════════════════════════════════════════════════════════════════════════════

def morning_digest_job():
    """
    MG-18: The autonomous morning digest — called by APScheduler.

    APScheduler runs this in a background daemon thread.
    It must be fully self-contained:
        - No user input
        - No CLI prompts
        - No shared mutable state with the agent

    CRITICAL — always wrap in try/except.
    APScheduler catches ALL exceptions silently. If this function raises
    an error, the scheduler logs it internally and schedules the next run.
    Without the try/except here, you would never see the traceback in
    your terminal and would have no idea the digest failed.
    """
    try:
        _run_digest()
    except Exception:
        print("\n[Digest ERROR] Morning digest failed with exception:")
        traceback.print_exc()   # prints the full stack trace to terminal
        print("[Digest ERROR] Will retry at the next scheduled time.\n")


def _run_digest():
    """
    The actual digest logic — separated from morning_digest_job() so you
    can call _run_digest() directly in tests without involving the scheduler.

    Steps:
        1. Authenticate + fetch emails from Gmail
        2. LLM triage → Top 5 most important emails
        3. Extract Urgent emails from triage results
        4. Detect unresponded emails via thread scan
        5. Print the formatted digest summary

    Future (Week 7+): replace print() with a push to the Genie chat API.
    """

    _print_header("MAIL GENIE — Morning Digest")

    # ── Step 1: Connect and fetch ─────────────────────────────────────────────
    print("[1/4] Connecting to Gmail...")
    service = get_gmail_service()

    # Fetch 100 emails to give the LLM enough signal for good triage.
    # 100 is a safe upper bound — Gmail API handles this in one paginated call.
    emails = get_recent_emails(service, max_results=100)
    print(f"      Fetched {len(emails)} emails.\n")

    # ── Step 2: Triage → Top 5 ───────────────────────────────────────────────
    print("[2/4] Running LLM triage...")

    # triage_emails() calls gpt-4o-mini with the full email list.
    # It returns a ranked list of up to 5 dicts with keys:
    #   rank, sender, subject, received, category, reason, unresponded
    triaged = triage_emails(emails)
    top5    = triaged[:5] if triaged else []

    if top5:
        print("\n  Top 5 Important Emails:")
        display_triage_table(top5)
    else:
        print("  Triage returned no results.\n")

    # ── Step 3: Urgent emails ─────────────────────────────────────────────────
    # triage_emails() already categorised each email.
    # We just filter the results — no extra LLM call needed.
    urgent = [e for e in triaged if e.get("category") == "Urgent"]

    if urgent:
        print(f"  Urgent emails requiring immediate attention: {len(urgent)}")
        for e in urgent:
            sender  = e.get("sender",  "Unknown")[:35]
            subject = e.get("subject", "(no subject)")[:40]
            print(f"    -> {sender}  |  {subject}")
        print()

    # ── Step 4: Unresponded detection ────────────────────────────────────────
    print("[3/4] Checking unresponded emails (thread scan)...")

    # detect_unresponded_emails() makes one Gmail API call per email that
    # passes the age + automated-sender pre-filters.
    # It scans each thread for the SENT label to check for a user reply.
    unresponded = detect_unresponded_emails(service, emails)

    if unresponded:
        print(f"\n  Unresponded ({len(unresponded)} emails):")
        display_unresponded_table(unresponded)
    else:
        print("  No unresponded emails found.\n")

    # ── Step 5: PRD escalation rule ──────────────────────────────────────────
    # MG-18 spec: "If >3 urgent/unresponded emails, send additional alert."
    # For prototype: we print an escalation banner.
    # For production: push a push notification here.
    total_attention = len(urgent) + len(unresponded)
    if total_attention > 3:
        print("  !! ESCALATION: More than 3 urgent/unresponded emails.")
        print(f"     Urgent: {len(urgent)}  |  Unresponded: {len(unresponded)}")
        print("     [Production: push notification would fire here]\n")

    # ── Step 6: Footer summary ────────────────────────────────────────────────
    print("[4/4] Digest complete.")
    print(f"      Top 5: {len(top5)}  |  Urgent: {len(urgent)}  |  Unresponded: {len(unresponded)}")
    _print_footer()


# ════════════════════════════════════════════════════════════════════════════════
# SCHEDULER SETUP
# ════════════════════════════════════════════════════════════════════════════════

def start_scheduler(dev_mode: bool = False) -> BackgroundScheduler:
    """
    Create, configure, and start the APScheduler BackgroundScheduler.

    BackgroundScheduler behaviour:
    - Runs in a daemon thread alongside the main process.
    - "Daemon" means: if the main process exits, this thread exits too.
      The scheduler does NOT keep the process alive on its own.
      That's why main() has a while True: time.sleep(60) loop below.
    - Jobs fire in that daemon thread — not in the main thread.
    - If a job is still running when the next trigger fires, APScheduler
      skips the second firing (default: max_instances=1).

    dev_mode=True  → interval trigger, every 30 seconds.
                     Use this to verify the job runs without waiting until 8 AM.

    dev_mode=False → cron trigger, weekdays at DIGEST_HOUR:DIGEST_MINUTE IST.
                     This is the production setting.

    Returns the running scheduler so main() can call scheduler.shutdown()
    on KeyboardInterrupt.
    """

    # Pass timezone to the scheduler — all cron times are interpreted in IST.
    scheduler = BackgroundScheduler(timezone=IST)

    if dev_mode:
        # DEV: fire every 30 seconds so you can immediately verify it works.
        # You'll see the digest header appear twice a minute in your terminal.
        scheduler.add_job(
            morning_digest_job,
            trigger="interval",
            seconds=30,
            id="morning_digest",
        )
        print(f"[Scheduler] DEV mode — digest fires every 30 seconds.")
        print(f"[Scheduler] Watch the terminal. Ctrl+C to stop.\n")

    else:
        # PROD: cron trigger.
        # day_of_week="mon-fri" means Monday (0) through Friday (4).
        # hour and minute are in the scheduler's timezone (IST, set above).
        scheduler.add_job(
            morning_digest_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=DIGEST_HOUR,
            minute=DIGEST_MINUTE,
            id="morning_digest",
        )
        print(f"[Scheduler] PROD mode — digest fires Mon-Fri at "
              f"{DIGEST_HOUR:02d}:{DIGEST_MINUTE:02d} IST.")

    scheduler.start()

    if not dev_mode:
        job = scheduler.get_job("morning_digest")
        if job and job.next_run_time:
            print(f"[Scheduler] Next run: {job.next_run_time.strftime('%A %Y-%m-%d %H:%M %Z')}")

    return scheduler


# ════════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════════

def main():
    """
    Start the scheduler and keep the process alive.

    Usage:
        python -m scheduler.digest_scheduler       # production
        python -m scheduler.digest_scheduler dev   # dev mode (30s interval)

    The while True loop keeps the main thread alive so the daemon scheduler
    thread doesn't get killed. We sleep in 60-second chunks so that
    Ctrl+C is responsive — without time.sleep(), the loop would spin the
    CPU at 100% doing nothing.

    On KeyboardInterrupt (Ctrl+C) or SystemExit:
        scheduler.shutdown() cleanly stops the background thread.
        Any in-progress job is allowed to finish before shutdown completes.
    """
    import sys

    # No argument     → DEV mode  (fires every 30s, for testing)
    # pass "prod"     → PROD mode (fires 8 AM IST weekdays)
    dev_mode = not (len(sys.argv) > 1 and sys.argv[1].lower() == "prod")

    scheduler = start_scheduler(dev_mode=dev_mode)

    print("Mail Genie scheduler running. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(60)   # keep main thread alive; sleep releases the GIL
    except (KeyboardInterrupt, SystemExit):
        print("\n[Scheduler] Shutting down...")
        scheduler.shutdown()     # waits for any running job to finish
        print("[Scheduler] Stopped cleanly.")


# ════════════════════════════════════════════════════════════════════════════════
# PRINT HELPERS
# ════════════════════════════════════════════════════════════════════════════════

def _print_header(title: str):
    width = 62
    print("\n" + "=" * width)
    padding = (width - len(title) - 2) // 2
    print(" " * padding + f" {title} " + " " * padding)
    print("=" * width + "\n")


def _print_footer():
    print("=" * 62 + "\n")


# ════════════════════════════════════════════════════════════════════════════════
# DIRECT TEST ENTRY — run digest once immediately without the scheduler
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()