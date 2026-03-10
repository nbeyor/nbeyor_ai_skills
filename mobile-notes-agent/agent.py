"""Claude-powered agent that interprets user messages and manages notes via tool-use."""

import json
import logging
from datetime import datetime

import anthropic

import spaces
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """\
You are a personal notes assistant that the user texts via Telegram. Think of yourself as a smart friend who keeps track of things for them.

Behavior guidelines:
- Be concise. Reply like a helpful friend texting back, not a formal app.
- Keep responses under 100 words unless the user asks to see a long list.
- Use one or two emoji max per message, only when natural.
- When the user mentions a space that doesn't exist, create it automatically with the right type.
- When listing items, include the item ID (e.g., "#3") so the user can reference them.
- If the user's message is ambiguous, ask a short clarifying question.
- For reminders, parse relative times ("tomorrow at 9am", "in 2 hours") into ISO 8601 timestamps.
- The current date and time is: {current_time}

You manage multiple "spaces" — separate collections for different purposes:
- **checklist** spaces: items with status (active/done) and optional priority. Great for todos, groceries, shopping lists.
- **notebook** spaces: entries with optional title and tags. Great for ideas, context/knowledge, journal entries, meeting notes.

Auto-route messages to the right space based on context. If no space fits, create one.
When a user says something like "add to my todo" route to the "todo" space, "new AI idea" route to "ai-ideas" space, etc.

You have tools to manage spaces and items within them. Use them to fulfill the user's requests.
"""

TOOLS = [
    {
        "name": "create_space",
        "description": "Create a new space (a separate collection/database). Use 'checklist' for things with done/not-done status, 'notebook' for freeform entries with titles and tags.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Short name for the space, lowercase with hyphens (e.g., 'todo', 'ai-ideas', 'book-recs').",
                },
                "display_name": {
                    "type": "string",
                    "description": "Human-readable name (e.g., 'Todo', 'AI Ideas', 'Book Recommendations').",
                },
                "space_type": {
                    "type": "string",
                    "enum": ["checklist", "notebook"],
                    "description": "Type of space. 'checklist' for items with done/active status; 'notebook' for freeform entries with title and tags.",
                },
                "description": {
                    "type": "string",
                    "description": "What this space is for.",
                },
            },
            "required": ["slug", "display_name", "space_type"],
        },
    },
    {
        "name": "list_spaces",
        "description": "List all spaces the user has, with item counts.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "add_item",
        "description": "Add an item to a space. Auto-creates the space if it doesn't exist. For checklists: provide content and optional priority. For notebooks: provide content and optional title/tags.",
        "input_schema": {
            "type": "object",
            "properties": {
                "space_slug": {
                    "type": "string",
                    "description": "Which space to add to (e.g., 'todo', 'ai-ideas', 'groceries').",
                },
                "content": {"type": "string", "description": "The item content."},
                "space_type": {
                    "type": "string",
                    "enum": ["checklist", "notebook"],
                    "description": "Type of space to create if it doesn't exist. Defaults to 'checklist'.",
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority (1=highest). Only for checklist spaces.",
                },
                "title": {
                    "type": "string",
                    "description": "Entry title. Only for notebook spaces.",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags. Only for notebook spaces.",
                },
            },
            "required": ["space_slug", "content"],
        },
    },
    {
        "name": "list_items",
        "description": "List items from a space. For checklists, filters by status (default: active). For notebooks, optionally filter by tag.",
        "input_schema": {
            "type": "object",
            "properties": {
                "space_slug": {
                    "type": "string",
                    "description": "Which space to list from.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "done"],
                    "description": "Filter by status (checklist only). Defaults to 'active'.",
                },
                "tag": {
                    "type": "string",
                    "description": "Filter by tag (notebook only).",
                },
            },
            "required": ["space_slug"],
        },
    },
    {
        "name": "update_item",
        "description": "Update an item in a space. Can mark done, edit content, change priority, update tags, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "space_slug": {
                    "type": "string",
                    "description": "Which space the item is in.",
                },
                "item_id": {"type": "integer", "description": "The item ID to update."},
                "content": {"type": "string", "description": "New content (optional)."},
                "status": {
                    "type": "string",
                    "enum": ["active", "done"],
                    "description": "New status (checklist only).",
                },
                "priority": {
                    "type": "integer",
                    "description": "New priority (checklist only).",
                },
                "title": {"type": "string", "description": "New title (notebook only)."},
                "tags": {"type": "string", "description": "New tags (notebook only)."},
            },
            "required": ["space_slug", "item_id"],
        },
    },
    {
        "name": "delete_item",
        "description": "Permanently delete an item from a space.",
        "input_schema": {
            "type": "object",
            "properties": {
                "space_slug": {
                    "type": "string",
                    "description": "Which space the item is in.",
                },
                "item_id": {"type": "integer", "description": "The item ID to delete."},
            },
            "required": ["space_slug", "item_id"],
        },
    },
    {
        "name": "search",
        "description": "Search across all spaces (or one specific space) by keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term."},
                "space_slug": {
                    "type": "string",
                    "description": "Optional: limit search to this space.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "set_reminder",
        "description": "Schedule a reminder to be sent at a specific time. Optionally link it to a space and item.",
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
                "space_slug": {
                    "type": "string",
                    "description": "Optional: link this reminder to a specific space.",
                },
                "item_id": {
                    "type": "integer",
                    "description": "Optional: link this reminder to a specific item in the space.",
                },
            },
            "required": ["remind_at", "message"],
        },
    },
]

# Map tool names to spaces functions
TOOL_HANDLERS = {
    "create_space": spaces.create_space,
    "list_spaces": spaces.list_spaces,
    "add_item": spaces.add_item,
    "list_items": spaces.list_items,
    "update_item": spaces.update_item,
    "delete_item": spaces.delete_item,
    "search": spaces.search,
    "set_reminder": spaces.set_reminder,
}

# In-memory conversation history per user (keyed by Telegram user ID)
_conversations: dict[int, list[dict]] = {}
MAX_HISTORY = 20


def _get_context_summary() -> str:
    """Build a brief summary of current spaces for context injection."""
    all_spaces = spaces.list_spaces()
    if not all_spaces:
        return "The user has no spaces yet. Create one when they ask to store something."
    parts = []
    for s in all_spaces:
        parts.append(f"{s['slug']} ({s['space_type']}): {s.get('item_count', 0)} items")
    return "Current spaces: " + "; ".join(parts)


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
