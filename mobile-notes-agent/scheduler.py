"""Scheduler for proactive reminder delivery via Telegram."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

import spaces
from config import REMINDER_CHECK_MINUTES

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _check_reminders(bot: Bot, chat_id: int) -> None:
    """Check for due reminders and send them."""
    due = spaces.get_due_reminders()
    for reminder in due:
        msg_parts = []
        if reminder.get("message"):
            msg_parts.append(reminder["message"])
        if reminder.get("linked_content"):
            msg_parts.append(f'(from {reminder.get("linked_space", "a space")}: "{reminder["linked_content"]}")')

        text = "\u23f0 Reminder: " + " ".join(msg_parts)
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            spaces.mark_reminder_sent(reminder["id"])
            logger.info("Sent reminder %d", reminder["id"])
        except Exception:
            logger.exception("Failed to send reminder %d", reminder["id"])


def start_scheduler(bot: Bot, chat_id: int) -> AsyncIOScheduler:
    """Start the reminder-checking scheduler."""
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _check_reminders,
        "interval",
        minutes=REMINDER_CHECK_MINUTES,
        args=[bot, chat_id],
        id="reminder_check",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started, checking reminders every %d minutes", REMINDER_CHECK_MINUTES)
    return _scheduler


def stop_scheduler() -> None:
    """Stop the scheduler if running."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
