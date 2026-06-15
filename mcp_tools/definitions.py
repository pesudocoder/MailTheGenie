# mcp_tools/definitions.py
# All 7 MCP tool definitions for Mail Genie.
# These are the JSON schemas sent to the LLM on every agent call.
# The LLM reads "description" to decide WHEN to use a tool.
# The LLM reads "parameters" to know WHAT to pass.
# No connector imports here — this file is pure data.


# ── Gmail Tools ───────────────────────────────────────────────────────────────

GMAIL_GET_MESSAGES = {
    "type": "function",
    "function": {
        "name": "gmail_get_messages",
        "description": (
            "Fetch recent emails from the user's Gmail inbox. "
            "Use this when the user asks to see, list, check, show, or retrieve their Gmail emails. "
            "Returns sender, subject, body preview, received time, and read status. "
            "Supports optional Gmail search query syntax (e.g. 'is:unread', 'from:ravi@client.com')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    # Integer type — LLM passes a number, not a string
                    "type": "integer",
                    "description": "Number of emails to fetch. Default is 10. Maximum is 50.",
                    "default": 10
                },
                "query": {
                    # Optional Gmail search string — same syntax as Gmail search bar
                    "type": "string",
                    "description": (
                        "Optional Gmail search query to filter emails. "
                        "Examples: 'is:unread', 'from:ravi@client.com', 'subject:invoice', 'newer_than:2d'."
                        "Leave empty to fetch latest emails with no filter."
                    ),
                    "default": ""
                }
            },
            # No required fields — both parameters have defaults
            "required": []
        }
    }
}


GMAIL_CREATE_DRAFT = {
    "type": "function",
    "function": {
        "name": "gmail_create_draft",
        "description": (
            "Create a draft email in Gmail without sending it. "
            "Use this when the user asks to draft, compose, or prepare a reply or new email. "
            "Always use this BEFORE sending — show the draft to the user for approval first. "
            "Returns a preview of the draft for the user to review."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_email": {
                    "type": "string",
                    "description": "Recipient email address. Example: 'ravi@client.com'."
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line."
                },
                "body": {
                    "type": "string",
                    "description": "Full email body text."
                },
                "thread_id": {
                    # Optional — only needed when replying to an existing thread
                    "type": "string",
                    "description": (
                        "Optional Gmail thread ID to attach this draft as a reply. "
                        "Leave empty for a new email."
                    ),
                    "default": ""
                }
            },
            # to_email, subject, body are always required — thread_id is optional
            "required": ["to_email", "subject", "body"]
        }
    }
}


GMAIL_SEND_MESSAGE = {
    "type": "function",
    "function": {
        "name": "gmail_send_message",
        "description": (
            "Send an email immediately via Gmail. "
            "IMPORTANT: Only call this tool after the user has explicitly confirmed they want to send. "
            "Never call this directly from a draft request — always show the draft first. "
            "Use gmail_create_draft first, show the preview, then call this only on confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_email": {
                    "type": "string",
                    "description": "Recipient email address."
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line."
                },
                "body": {
                    "type": "string",
                    "description": "Full email body text."
                },
                "thread_id": {
                    "type": "string",
                    "description": (
                        "Optional Gmail thread ID to send this as a reply in an existing thread. "
                        "Leave empty for a new email."
                    ),
                    "default": ""
                }
            },
            "required": ["to_email", "subject", "body"]
        }
    }
}


GMAIL_GET_THREADS = {
    "type": "function",
    "function": {
        "name": "gmail_get_threads",
        "description": (
            "Fetch email threads from Gmail. A thread groups all replies in the same conversation. "
            "Use this when the user asks about a conversation, email chain, or thread. "
            "Also use this to find the thread_id needed before drafting a reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Number of threads to fetch. Default is 10.",
                    "default": 10
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Optional Gmail search query to filter threads. "
                        "Examples: 'from:ravi@client.com', 'subject:contract', 'is:unread'."
                    ),
                    "default": ""
                }
            },
            "required": []
        }
    }
}


# ── Outlook Tools ─────────────────────────────────────────────────────────────

OUTLOOK_GET_MESSAGES = {
    "type": "function",
    "function": {
        "name": "outlook_get_messages",
        "description": (
            "Fetch recent emails from the user's Outlook inbox. "
            "Use this when the user asks to see, list, check, or retrieve their Outlook emails. "
            "Returns sender, subject, body preview, received time, and read status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Number of emails to fetch. Default is 10. Maximum is 50.",
                    "default": 10
                }
            },
            "required": []
        }
    }
}


OUTLOOK_CREATE_DRAFT = {
    "type": "function",
    "function": {
        "name": "outlook_create_draft",
        "description": (
            "Create a draft email in Outlook without sending it. "
            "Use this when the user asks to draft, compose, or prepare a reply or new email via Outlook. "
            "Always use this BEFORE sending — show the draft to the user for approval first. "
            "Returns a preview of the draft for the user to review."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_email": {
                    "type": "string",
                    "description": "Recipient email address. Example: 'ravi@client.com'."
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line."
                },
                "body": {
                    "type": "string",
                    "description": "Full email body text."
                }
            },
            "required": ["to_email", "subject", "body"]
        }
    }
}


OUTLOOK_SEND_MESSAGE = {
    "type": "function",
    "function": {
        "name": "outlook_send_message",
        "description": (
            "Send an email immediately via Outlook. "
            "IMPORTANT: Only call this tool after the user has explicitly confirmed they want to send. "
            "Never call this directly from a draft request — always show the draft first. "
            "Use outlook_create_draft first, show the preview, then call this only on confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_email": {
                    "type": "string",
                    "description": "Recipient email address."
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line."
                },
                "body": {
                    "type": "string",
                    "description": "Full email body text."
                }
            },
            "required": ["to_email", "subject", "body"]
        }
    }
}


# ── Master list — this is what gets passed to the LLM ─────────────────────────
# The agent imports ALL_TOOLS and passes it directly to client.chat.completions.create()
# as the tools= parameter. Order doesn't matter — the LLM reads descriptions, not position.

ALL_TOOLS = [
    GMAIL_GET_MESSAGES,
    GMAIL_CREATE_DRAFT,
    GMAIL_SEND_MESSAGE,
    GMAIL_GET_THREADS,
    OUTLOOK_GET_MESSAGES,
    OUTLOOK_CREATE_DRAFT,
    OUTLOOK_SEND_MESSAGE,
]

# Convenient lookup: tool name → definition
# Used in executor.py to validate that a tool_call name is known before dispatching
TOOL_NAMES = {tool["function"]["name"] for tool in ALL_TOOLS}