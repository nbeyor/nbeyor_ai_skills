"""Telegram bot entry point for the mobile notes agent."""

import logging
import sys

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

import agent
import storage
from config import ALLOWED_USER_IDS, TELEGRAM_BOT_TOKEN
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _is_allowed(user_id: int) -> bool:
    """Check if a user is in the allowlist. Empty list = allow all."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "Hey! I'm your notes assistant. You can tell me things to remember, "
        "ask me to manage lists, or set reminders.\n\n"
        "Just text me naturally — no special commands needed. Try:\n"
        '• "Add to my todo: call dentist"\n'
        '• "Show my AI ideas"\n'
        '• "Remind me to buy milk tomorrow at 9am"\n'
        '• "What lists do I have?"'
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all text messages by forwarding to the Claude agent."""
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        reply = await agent.handle_message(user_id, update.message.text)
        await update.message.reply_text(reply)
    except Exception:
        logger.exception("Error handling message from user %d", user_id)
        await update.message.reply_text(
            "Sorry, something went wrong. Try again in a moment."
        )


async def post_init(application) -> None:
    """Called after the application is initialized — start the scheduler."""
    # Use the first allowed user ID as the chat ID for reminders.
    # For a personal bot, this is the owner's user ID (same as chat ID in DMs).
    if ALLOWED_USER_IDS:
        chat_id = ALLOWED_USER_IDS[0]
        start_scheduler(application.bot, chat_id)
        logger.info("Reminder scheduler started for chat_id=%d", chat_id)
    else:
        logger.warning(
            "No ALLOWED_USER_IDS set — reminders won't be sent. "
            "Set ALLOWED_USER_IDS in .env to enable proactive reminders."
        )


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set. Copy .env.example to .env and fill it in.")
        sys.exit(1)

    storage.init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot starting in polling mode...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
