---
name: mobile-notes-agent
description: >
  A Telegram-based personal notes assistant powered by Claude. Manages categorized notes
  (to-do lists, ideas, etc.), supports natural language interaction, and sends proactive
  reminders. Use this skill when discussing the mobile notes agent setup, its architecture,
  deployment, or when troubleshooting the Telegram bot.
---

# Mobile Notes Agent

## Overview

A single-process Python service that acts as an intelligent notes assistant via Telegram. The user texts it naturally and it manages categorized notes, to-do lists, and time-based reminders using Claude's tool-use capability.

## Architecture

```
Phone (Telegram) → Bot (python-telegram-bot) → Agent (Claude API tool-use) → Storage (SQLite)
                                                                              ↑
                                        Scheduler (APScheduler) ──────────────┘
```

## Components

| File | Purpose |
|------|---------|
| `bot.py` | Entry point. Telegram bot setup, message routing, security check. |
| `agent.py` | Claude API integration. System prompt, tool definitions, tool-use loop. |
| `storage.py` | SQLite schema and CRUD. Notes, categories, reminders. |
| `scheduler.py` | APScheduler. Checks for due reminders and sends them via Telegram. |
| `config.py` | Environment variable loading. |

## Setup

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram to create a bot and get a token
2. Get your Telegram user ID by messaging [@userinfobot](https://t.me/userinfobot)
3. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, and `ALLOWED_USER_IDS`
4. `pip install -r requirements.txt`
5. `python bot.py`

## Key Design Decisions

- **Natural language only**: No slash commands (except /start). Claude interprets intent via tool-use.
- **Implicit categories**: Categories are created automatically from natural language. No setup needed.
- **SQLite**: Single-file database, stdlib, concurrent-safe. Notes persist across restarts.
- **Single process**: Async Python handles Telegram polling, Claude calls, and scheduled reminders. No queues or workers needed for a personal tool.
- **Conversation memory**: Last 20 messages kept in memory per user. Notes are the persistent artifact, not chat logs.
