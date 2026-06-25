# agents/mail_genie_agent.py
# Week 5 — Mail Genie Agent
# Implements MG-06 (top 5), MG-07 (categories), MG-10 (table output), MG-14 (send confirmation)
#
# Run from MAILTHEGENIE/ root:
#   python -m agents.mail_genie_agent

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

# ── Import your existing modules ──────────────────────────────────────────────
# These were built in Weeks 1-4. The agent orchestrates them.
from mcp_tools.executor import execute_tool, parse_tool_args
from mcp_tools.definitions import ALL_TOOLS
from agents.triage_agent import triage_emails, display_triage_table

load_dotenv()
client = OpenAI()

# ── System Prompt ─────────────────────────────────────────────────────────────
# This is the agent's identity, rules, and output format — sent on every LLM call.
# The LLM reads this and shapes every response to match.

SYSTEM_PROMPT = """
You are Mail Genie, an AI-powered email agent for busy professionals.

You help users:
- View and triage their emails (Gmail + Outlook)
- See top 5 most important emails (MG-06)
- Filter by category: Urgent, Important/Client, Social, Newsletter (MG-07)
- Detect emails that need a reply but haven't received one (MG-08)
- Draft context-aware replies (MG-12)
- Send emails — but ONLY after the user explicitly confirms (MG-14)

OUTPUT FORMAT (MG-10):
When showing a list of emails, always use this table format:
  Sender | Subject | Time | Category | Reason
Add a ⚠️ flag next to any unresponded email.

CRITICAL SAFETY RULE (MG-14):
NEVER call gmail_send_message or outlook_send_message unless the user has
explicitly typed "confirm send", "send it", or "yes send".
If the user asks to send without confirming, show the draft preview and
say: "Reply with 'confirm send' to send this."

ID MASKING (MG-03):
Never mention raw message IDs, draft IDs, or thread IDs to the user.
Use friendly labels like "Draft saved" or "Reply to Ravi".

REASONING STYLE:
1. Always fetch emails first before triaging.
2. For "top emails" or "important emails" queries, fetch then triage.
3. For "draft a reply to X", find the thread first, then create a draft.
4. Be concise. The user is busy.
""".strip()


# ── Conversation State ────────────────────────────────────────────────────────
# This dict persists for the lifetime of one CLI session.
# It lets us track: has a draft been created? Has the user confirmed send?
# This is the MG-14 confirmation guard state.

def make_fresh_state():
    """Returns a clean state dict for a new session."""
    return {
        "pending_draft":    None,   # draft preview shown to user
        "pending_draft_id": None,   # actual Gmail draft ID (internal, never shown)
        "send_confirmed":   False,  # True only after exact confirmation phrase
        "last_email_list":  [],
    }


# ── The Agent Loop ────────────────────────────────────────────────────────────
# This is the core of Week 5. It's a while loop that:
#   1. Calls the LLM with the full message history + tools
#   2. If finish_reason == "tool_calls": execute each tool, append result, loop again
#   3. If finish_reason == "stop": return the final message to the user

def run_agent(user_message: str, messages: list, state: dict) -> str:
    """
    Runs one user turn of the Mail Genie agent.

    Args:
        user_message: The raw string the user typed.
        messages:     The full conversation history (mutated in place).
        state:        Persistent session state (draft tracking, confirmation).

    Returns:
        The agent's final response string to show the user.
    """


   # MG-14 fix: exact set membership, not substring search.
    # "don't send it" contains "send it" — substring match is unsafe.
    # Strip + lower + check against a set of exact phrases only.
    CONFIRM_PHRASES = {
        "confirm send", "send it", "yes", "yes send",
        "go ahead", "go ahead and send", "confirm", "do it"
    }
    if user_message.strip().lower() in CONFIRM_PHRASES:
        if state.get("pending_draft_id"):
            state["send_confirmed"] = True
        else:
            # User said "confirm send" but no draft is pending
            messages.append({"role": "user", "content": user_message})
            return "No draft is pending. Ask me to draft a reply first."

    # Append the user's message to the conversation history.
    # Every LLM call gets the full history — this is how it knows what happened before.
    messages.append({"role": "user", "content": user_message})

    # ── Agent Loop ─────────────────────────────────────────────────────────────
    # We loop until finish_reason == "stop". Each iteration is one LLM call.
    # On average: "top emails" = 2 iterations (fetch → triage → stop)
    #             "draft reply" = 3 iterations (find thread → create draft → stop)

    max_iterations = 8  # Safety cap — prevents infinite loops on edge cases
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        # ── Call the LLM ───────────────────────────────────────────────────────
        # We pass:
        #   model:    gpt-4o-mini (consistent with rest of project)
        #   messages: full history — LLM sees every prior tool result
        #   tools:    ALL_TOOLS from mcp_tools/definitions.py (7 schemas)
        #   tool_choice: "auto" — LLM decides whether to call a tool or not
        #
        # The LLM does NOT execute tools. It just says "I want to call X with Y args."
        # WE execute the tool and feed the result back.

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            tools=ALL_TOOLS,
            tool_choice="auto",
            max_tokens=2000,
        )

        choice = response.choices[0]
        finish_reason = choice.finish_reason

        # ── Case 1: LLM wants to call one or more tools ────────────────────────
        if finish_reason == "tool_calls":
            assistant_message = choice.message

            # Append the assistant's tool-call request to history.
            # This is required — the LLM expects to see its own prior requests
            # when it gets the tool results back.
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,  # Usually None for tool calls
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in assistant_message.tool_calls
                ]
            })

            # Execute each tool the LLM requested (usually just one at a time)
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args_str = tool_call.function.arguments

                # ── MG-14 Confirmation Guard ───────────────────────────────────
                # Even if the LLM tries to call send_message, we intercept here.
                # The LLM can't bypass this — we control execution, not the LLM.
                if tool_name in ("gmail_send_message", "outlook_send_message"):
                    if not state.get("send_confirmed"):
                        # Block — no confirmation yet
                        tool_result = json.dumps({
                            "status":  "blocked",
                            "message": (
                                "Send blocked. Draft is ready for review. "
                                "Tell the user to type exactly 'confirm send' to send."
                            )
                        })
                        messages.append({
                            "role":         "tool",
                            "tool_call_id": tool_call.id,
                            "content":      tool_result,
                        })
                        continue

                    # User confirmed — use send_draft() if we have a draft ID
                    # This sends the exact draft the user reviewed, not a new message
                    if state.get("pending_draft_id"):
                        from connectors.gmail_connector import send_draft
                        from connectors.gmail_connector import get_gmail_service
                        try:
                            svc    = get_gmail_service()
                            result = send_draft(svc, state["pending_draft_id"])
                            tool_result = json.dumps({
                                "status":  "sent",
                                "message": "Email sent successfully."
                            })
                        except Exception as e:
                            tool_result = json.dumps({
                                "status": "error",
                                "message": f"Send failed: {e}"
                            })
                        finally:
                            # Reset state regardless of outcome
                            state["send_confirmed"]   = False
                            state["pending_draft_id"] = None
                            state["pending_draft"]    = None
                        messages.append({
                            "role":         "tool",
                            "tool_call_id": tool_call.id,
                            "content":      tool_result,
                        })
                        continue
                    else:
                        # No draft ID — let the LLM's tool call proceed normally
                        state["send_confirmed"] = False

                # ── Normal Tool Execution ──────────────────────────────────────
                # parse_tool_args converts the LLM's JSON string to a dict.
                # execute_tool dispatches to the right connector function.
                # Both always return a string (JSON) — they never raise.
                tool_args = parse_tool_args(tool_args_str)
                tool_result = execute_tool(tool_name, tool_args)

                # If this was a message fetch, store for potential triage later
                # If this was a message fetch, store for triage
                if tool_name in ("gmail_get_messages", "outlook_get_messages"):
                    try:
                        fetched = json.loads(tool_result)
                        if isinstance(fetched, list):
                            state["last_email_list"].extend(fetched)
                    except Exception:
                        pass

                # If this was a draft creation, store the draft ID internally
                # The ID comes from gmail_connector.create_draft()'s "_draft_id" key
                # Never shown to user — used only to call send_draft() on confirmation
                if tool_name == "gmail_create_draft":
                    try:
                        draft_result = json.loads(tool_result)
                        if draft_result.get("_draft_id"):
                            state["pending_draft_id"] = draft_result["_draft_id"]
                            state["pending_draft"]    = draft_result.get("preview", "")
                    except Exception:
                        pass

                # Append the tool result to history.
                # The role must be "tool" and tool_call_id must match the request.
                # Without this exact structure, the LLM won't recognise the result.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })

            # Loop continues — LLM will now see the tool results and decide next step

        # ── Case 2: LLM has a final answer ────────────────────────────────────
        elif finish_reason == "stop":
            final_text = choice.message.content or ""

            # Append the final assistant message to history for context in future turns
            messages.append({"role": "assistant", "content": final_text})

            return final_text

        # ── Case 3: Unexpected finish reason ──────────────────────────────────
        else:
            return f"⚠️ Unexpected finish reason: {finish_reason}. Please try again."

    # If we exit the loop without a "stop", something went wrong
    return "⚠️ Agent reached max iterations without a final answer. Please rephrase your request."


# ── CLI Entry Point ───────────────────────────────────────────────────────────
# This is the interactive chat loop you run from the terminal.
# It maintains:
#   messages: list — grows every turn (the full conversation)
#   state:    dict — persists draft/confirmation info across turns

def main():
    print("\n✉️  Mail Genie Agent — Week 5")
    print("   Connects to Gmail + Outlook via MCP tools")
    print("   Type 'quit' or 'exit' to stop\n")
    print("   Try: 'What are my top emails?'")
    print("        'Show urgent emails'")
    print("        'Show newsletters'")
    print("        'Draft a reply to Ravi'\n")
    print("-" * 55)

    messages = []       # Conversation history — grows each turn
    state = make_fresh_state()   # Session state — tracks drafts, confirmations

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "bye"):
            print("\nMail Genie: Goodbye! Have a productive day. 📬")
            break

        print("\nMail Genie: ", end="", flush=True)

        try:
            response = run_agent(user_input, messages, state)
            print(response)
        except Exception as e:
            print(f"⚠️  Error: {e}")
            print("    Please try again or rephrase your request.")


if __name__ == "__main__":
    main()