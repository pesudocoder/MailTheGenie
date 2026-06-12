# agents/triage_agent.py
# Production version of email triage — moved from week-2/email_triage.py

import json
import os
from dotenv import load_dotenv
from openai import OpenAI 

# ── 1. Load your .env file ────────────────────────────────────────────────────
load_dotenv()

# ── 2. Configure OpenAI Client to route through OpenRouter ────────────────────
client = OpenAI()


# ── 3. System prompt ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are an expert email triage assistant for a busy professional.

Your job is to analyse a list of emails and identify the TOP 5 most important ones.

CATEGORIES (use exactly these strings):
- "Urgent"           → requires immediate action, time-sensitive, or from a client/exec
- "Important/Client" → client communication, deal-related, or from key stakeholders  
- "Social"           → casual conversation, team updates, non-urgent internal
- "Newsletter"       → marketing emails, subscriptions, automated digests

RANKING RULES:
1. Client emails with no reply over 24 hours → always rank highest
2. Emails from executives or with deadlines → rank second
3. Financial or invoice emails → rank third
4. Deadline-bearing emails → rank fourth
5. Active sales or proposal threads → rank fifth

UNRESPONDED FLAG:
Set "unresponded": true if the email is from a client or exec AND seems to need a reply.

OUTPUT FORMAT:
Return ONLY a valid JSON array of exactly 5 objects matching the required schema structure.
""".strip()

# ── 4. Triage function ────────────────────────────────────────────────────────
def triage_emails(emails: list) -> list:
    """
    Sends emails to OpenRouter and gets back top 5 ranked + categorised.
    """

    # Format emails into readable text
    email_text = ""
    for i, email in enumerate(emails, start=1):
        email_text += f"""
Email {i}:
  Sender:   {email.get('sender', 'Unknown')}
  Subject:  {email.get('subject', '(no subject)')}
  Received: {email.get('received_at', 'Unknown')}
  Body:     {email.get('body', '')[:500]}
"""

    full_user_prompt = f"Here are {len(emails)} emails from my inbox. Please triage them:\n{email_text}"

    # Define the structure the free model must reply with
    json_schema = {
        "name": "email_triage_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "triaged_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rank": {"type": "number"},
                            "sender": {"type": "string"},
                            "subject": {"type": "string"},
                            "received": {"type": "string"},
                            "category": {"type": "string"},
                            "reason": {"type": "string"},
                            "unresponded": {"type": "boolean"}
                        },
                        "required": ["rank", "sender", "subject", "received", "category", "reason", "unresponded"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["triaged_list"],
            "additionalProperties": False
        }
    }

    try:
        # Call OpenRouter using a completely free model endpoint
        response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_user_prompt}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": json_schema
            }
        )
        
        # Parse the reliable JSON response structure
        response_data = json.loads(response.choices[0].message.content)
        return response_data.get("triaged_list", [])

    except Exception as e:
        print(f"⚠️  An error occurred during OpenRouter triage: {e}")
        return []

# ── 5. Display function ───────────────────────────────────────────────────────
def display_triage_table(triaged_emails: list):
    if not triaged_emails:
        print("No emails to display.")
        return

    print("\n" + "=" * 95)
    print(f"  {'#':<4} {'Sender':<26} {'Subject':<28} {'Category':<18} {'Reason'}")
    print("=" * 95)

    for email in triaged_emails:
        rank     = email.get("rank", "?")
        sender   = email.get("sender", "Unknown")[:25]
        subject  = email.get("subject", "(no subject)")[:27]
        category = email.get("category", "Unknown")
        reason   = email.get("reason", "")
        flag     = "  ⚠️ " if email.get("unresponded") else ""

        print(f"  {rank:<4} {sender:<26} {subject:<28} {category:<18} {reason}{flag}")

    print("=" * 95)

    unresponded = [e for e in triaged_emails if e.get("unresponded")]
    if unresponded:
        print(f"\n⚠️  {len(unresponded)} email(s) flagged as unresponded:")
        for e in unresponded:
            print(f"   → {e.get('sender')} — \"{e.get('subject')}\"")
    print()

# ── 6. Sample emails for testing ─────────────────────────────────────────────
SAMPLE_EMAILS = [
    {"sender": "ravi@client.com", "subject": "Contract Revision — URGENT", "body": "Hi, we need to discuss clause 4.2 before end of week. Please respond ASAP.", "received_at": "Today 9:15 AM"},
    {"sender": "ceo@company.com", "subject": "Q2 Review — action needed", "body": "Team, I need everyone's input on the Q2 numbers before Thursday board meeting.", "received_at": "Yesterday 6:00 PM"},
    {"sender": "newsletter@medium.com", "subject": "Your weekly tech digest", "body": "This week in tech: AI advances, new frameworks, and more...", "received_at": "Today 7:00 AM"},
    {"sender": "vendor@supply.co", "subject": "Invoice #1042 overdue", "body": "This is a reminder that invoice #1042 for $4,200 is 15 days overdue.", "received_at": "2 days ago"},
    {"sender": "hr@company.com", "subject": "Policy update — sign by Friday", "body": "Please review and sign the updated remote work policy by this Friday.", "received_at": "Today 8:00 AM"},
    {"sender": "john@bigcorp.com", "subject": "Proposal feedback", "body": "I reviewed your proposal and have some questions. Can we get on a call?", "received_at": "Today 11:00 AM"},
    {"sender": "friend@gmail.com", "subject": "Weekend plans?", "body": "Hey! Are you free this Saturday for a get-together?", "received_at": "Yesterday 3:00 PM"},
    {"sender": "promo@shopping.com", "subject": "50% off — today only!", "body": "Massive sale on electronics. Use code SAVE50 at checkout.", "received_at": "Today 6:30 AM"}
]

# ── 7. Run it ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🔍 Mail Genie — Email Triage ")
    print(f"   Analysing {len(SAMPLE_EMAILS)} emails...\n")

    results = triage_emails(SAMPLE_EMAILS)

    if results:
        display_triage_table(results)
    else:
        print("Triage failed. Check the error above.")