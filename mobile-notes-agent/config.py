"""Configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Comma-separated Telegram user IDs that are allowed to interact with the bot.
# Leave empty to allow anyone (not recommended for production).
ALLOWED_USER_IDS = [
    int(uid.strip())
    for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
]

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "notes.db"))
REMINDER_CHECK_MINUTES = int(os.environ.get("REMINDER_CHECK_MINUTES", "5"))

# Claude model to use for the agent
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
