---
name: mobile-notes-agent
description: >
  A Telegram-based personal notes assistant powered by Claude. Manages multiple "spaces"
  (checklists, notebooks) as separate SQLite databases, supports natural language interaction,
  and sends proactive reminders. Deploys to Fly.io with persistent volumes.
  Use this skill when discussing the mobile notes agent setup, its architecture,
  deployment, or when troubleshooting the Telegram bot.
---

# Mobile Notes Agent

## Overview

A single-process Python service that acts as an intelligent notes assistant via Telegram. The user texts it naturally and it manages multiple spaces (checklists, notebooks), each backed by its own SQLite database, with time-based reminders powered by Claude's tool-use capability.

## Architecture

```
Phone (Telegram) → Bot (python-telegram-bot) → Agent (Claude API tool-use) → Spaces (multi-SQLite)
                                                                              ↑
                                        Scheduler (APScheduler) ──────────────┘
```

## Components

| File | Purpose |
|------|---------|
| `bot.py` | Entry point. Telegram bot setup, message routing, security check. |
| `agent.py` | Claude API integration. System prompt, tool definitions, tool-use loop. |
| `spaces.py` | Multi-space storage manager. Each space is its own SQLite database. |
| `scheduler.py` | APScheduler. Checks for due reminders and sends them via Telegram. |
| `config.py` | Environment variable loading. |

## Multi-Space Storage

Each "space" is a separate SQLite database file in `DATA_DIR`:

- **checklist** spaces: items with status (active/done) and priority. For todos, groceries, etc.
- **notebook** spaces: entries with title, content, and tags. For ideas, knowledge, journal, etc.

A central `meta.db` tracks all spaces and holds global reminders.

```
data/
├── meta.db          # Space registry + reminders
├── todo.db          # checklist
├── ai-ideas.db      # notebook
└── ...              # dynamically created
```

## Setup

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram to create a bot and get a token
2. Get your Telegram user ID by messaging [@userinfobot](https://t.me/userinfobot)
3. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, and `ALLOWED_USER_IDS`
4. `pip install -r requirements.txt`
5. `python bot.py`

## Deployment (Fly.io)

Uses Fly.io with a persistent volume for SQLite data. See `fly.toml` for config.
Auto-deploys via GitHub Actions on push to `main` (see `.github/workflows/deploy.yml`).

First-time setup:
```bash
fly launch --no-deploy --name mobile-notes-agent --region ewr
fly volumes create notes_data --region ewr --size 1
fly secrets set TELEGRAM_BOT_TOKEN="..." ANTHROPIC_API_KEY="..." ALLOWED_USER_IDS="..."
fly deploy --remote-only
```

## Key Design Decisions

- **Multi-space architecture**: Each space is its own SQLite file with its own schema, created dynamically.
- **Natural language only**: No slash commands (except /start). Claude auto-routes to the right space.
- **Two space types**: Checklists (items + status) and notebooks (entries + title + tags).
- **Global reminders**: Stored in meta.db, can reference items in any space.
- **Single process**: Async Python handles Telegram polling, Claude calls, and scheduled reminders.
- **Conversation memory**: Last 20 messages kept in memory per user.
