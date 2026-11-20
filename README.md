# Internship Role Watcher

A dependency-free Python watcher that checks the
[Singapore Summer 2026 Tech Internships list](https://github.com/didtheyghostme/Singapore-Summer2026-TechInternships)
at 7:17 AM and 7:17 PM Singapore time and sends matching new roles to Telegram.

## Setup

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather), then send
   the bot a message.
2. Get your chat ID from
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`.
3. In this repository, open **Settings → Secrets and variables → Actions** and
   add these repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Optionally add a repository variable named `ROLE_KEYWORDS` containing a
   comma-separated list. The default is
   `software,swe,engineer,developer,backend,full stack,fullstack,data,ai,ml`.
   Set the variable to an empty value to match every new role.
5. Enable GitHub Actions. The first run only records existing rows, so it does
   not send hundreds of backlog alerts.

The workflow commits `state/seen_rows.json` to `main` after each change.
Repository settings must allow GitHub Actions to create and approve commits
with read/write workflow permissions.

## Manual test

Open **Actions → Watch internships → Run workflow**. A run with the initial
empty state seeds the current rows without sending a message. To test delivery,
remove one hash from `state/seen_rows.json`, commit that change, and run the
workflow again.

Run locally with Python 3.12:

```sh
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python watcher.py
```
