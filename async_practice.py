import asyncio
import time

INBOX_A = {"name":"gmail", "delay": 2.0 ,"emails": ["Contract Update", "Team Standup", "Invoice #1042"]} 
INBOX_B= {"name":"outlook", "delay": 1.5 ,"emails": ["Project Proposal", "Client Feedback", "Budget Report"]}
INBOX_C={"name":"gmail-work", "delay": 0.5 ,"emails": ["Meeting Agenda", "Performance Review", "Holiday Schedule"]}

async def fetch_emails(inbox):
    await asyncio.sleep(inbox["delay"])
    return inbox["emails"]

async def main():
    start =time.perf_counter()
    a_emails, b_emails, c_emails = await asyncio.gather(
        fetch_emails(INBOX_A),
        fetch_emails(INBOX_B),
        fetch_emails(INBOX_C),
    )
    elapsed = time.perf_counter() - start
    print(f"Fetchd all emails in {elapsed : .1f} s \n")
    all_results = zip([INBOX_A, INBOX_B, INBOX_C], [a_emails, b_emails, c_emails])
    total = 0 
    for inbox, emails in all_results:
        print(f"{inbox['name']} ({len(emails)} emails)")
        for subject in emails:
            print(f"  - {subject}")
        total += len(emails)

    print(f"\nTotal: {total} emails")
asyncio.run(main())
    

