"""Claude-powered agent that interprets user messages and manages notes via tool-use."""

import json
import logging
from datetime import datetime

import anthropic

import storage
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """\
You are a personal notes assistant that the user texts via Telegram. Think of yourself as a smart friend who keeps track of things for them.

Behavior guidelines:
- Be concise. Reply like a helpful friend texting back, not a formal app.
- Keep responses under 100 words unless the user asks to see a long list.
- Use one or two emoji max per message, only when natural.
- When the user mentions a category that doesn't exist, create it automatically.
- When listing notes, include the note ID (e.g., "#3") so the user can reference them.
- If the user's message is ambiguous, ask a short clarifying question.
- For reminders, parse relative times ("tomorrow at 9am", "in 2 hours") into ISO 8601 timestamps.
- The current date and time is: {current_time}

You have tools to manage notes. Use them to fulfill the user's requests.
"""

TOOLS = [
    {
        "name": "add_note",
        "description": "Add a note to a category. Auto-creates the category if it doesn't exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The note content"},
                "category": {
                    "type": "string",
                    "description": "Category name (e.g., 'todo', 'ai-ideas', 'groceries'). Use lowercase with hyphens.",
                },
            },
            "required": ["content", "category"],
        },
    },
    {
        "name": "list_notes",
        "description": "List notes, optionally filtered by category and/or status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category name to filter by. Omit to list all.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "done"],
                    "description": "Filter by status. Defaults to 'active'.",
                },
            },
        },
    },
    {
        "name": "mark_done",
        "description": "Mark a note as done by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "The note ID to mark as done"},
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "delete_note",
        "description": "Permanently delete a note by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "The note ID to delete"},
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "list_categories",
        "description": "List all note categories with their active and done counts.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "set_reminder",
        "description": "Schedule a reminder to be sent at a specific time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "remind_at": {
                    "type": "string",
                    "description": "ISO 8601 datetime for when to send the reminder (e.g., '2025-01-15T09:00:00').",
                },
                "message": {
                    "type": "string",
                    "description": "The reminder message to send.",
                },
                "note_id": {
                    "type": "integer",
                    "description": "Optional: link this reminder to a specific note ID.",
                },
            },
            "required": ["remind_at", "message"],
        },
    },
    {
        "name": "search_notes",
        "description": "Search across all notes by keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
            },
            "required": ["query"],
        },
    },
]

# Map tool names to storage functions
TOOL_HANDLERS = {
    "add_note": storage.add_note,
    "list_notes": storage.list_notes,
    "mark_done": storage.mark_done,
    "delete_note": storage.delete_note,
    "list_categories": storage.list_categories,
    "set_reminder": storage.set_reminder,
    "search_notes": storage.search_notes,
}

# In-memory conversation history per user (keyed by Telegram user ID)
_conversations: dict[int, list[dict]] = {}
MAX_HISTORY = 20


def _get_context_summary() -> str:
    """Build a brief summary of current categories for context injection."""
    categories = storage.list_categories()
    if not categories:
        return "The user has no notes yet."
    parts = []
    for cat in categories:
        active = cat.get("active_count") or 0
        done = cat.get("done_count") or 0
        parts.append(f"{cat['name']}: {active} active, {done} done")
    return "Current notes summary: " + "; ".join(parts)


def _execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return its result as a JSON string."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = handler(**input_data)
        return json.dumps(result, default=str)
    except Exception as e:
        logger.exception("Tool execution error: %s", name)
        return json.dumps({"error": str(e)})


async def handle_message(user_id: int, text: str) -> str:
    """Process a user message and return the agent's text reply."""
    # Build conversation history
    history = _conversations.setdefault(user_id, [])
    history.append({"role": "user", "content": text})

    # Trim to max history
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    system = SYSTEM_PROMPT.format(current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    context = _get_context_summary()
    full_system = f"{system}\n\n{context}"

    # Tool-use loop: keep calling Claude until we get a final text response
    messages = list(history)
    while True:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=full_system,
            tools=TOOLS,
            messages=messages,
        )

        # Collect text and tool use blocks
        text_parts = []
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # If no tool calls, we're done
        if not tool_uses:
            reply = "\n".join(text_parts) or "Done."
            history.append({"role": "assistant", "content": reply})
            return reply

        # Execute tools and feed results back
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        tool_results = []
        for tool_use in tool_uses:
            result = _execute_tool(tool_use.name, tool_use.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    # Unreachable, but just in case
    return "Something went wrong. Please try again."
