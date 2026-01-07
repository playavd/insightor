# Insightor-AGR Bot

A Telegram bot for monitoring [Bazaraki](https://www.bazaraki.com) car ads.

## Architecture
- **Admin Bot**: Manages the scraper and system status.
- **User Bot (Client)**: Allows users to create alerts and receive notifications.
- **Scraper Service**: Periodically checks for new/updated ads.
- **Database**: SQLite (`insightor.db`).

## Setup
1. Copy `.env.example` to `.env` and fill in tokens.
2. Run `pip install -r requirements.txt`.
3. Run `python3 main.py`.

## Smoke Test Checklist (Regression Testing)

After any code changes, perform the following manual checks:

### 1. Startup
- [ ] Run `python3 main.py`.
- [ ] Verify logs show "Database initialized" and "Admin Bot polling starting...".
- [ ] Ensure no immediate traceback.

### 2. Client Bot Flow
- [ ] Send `/start` to User Bot. -> Should show Main Menu.
- [ ] Click "🔔 New Alert". -> Should open Wizard (Dashboard).
- [ ] Create a "Brand: Toyota" alert (select Toyota, Any Model, etc.). -> Should Save.
- [ ] Click "🗂️ My Alerts". -> Should list the new alert.
- [ ] Select the alert -> Click "Deactivate" then "Activate". -> Should toggle status.
- [ ] Delete the alert.

### 3. Scraper Cycle
- [ ] Observe logs for "Scheduler Trigger: Starting scraper cycle".
- [ ] Check if "Found X ads" appears in logs.
- [ ] Ensure `notify_user` is triggered (debug log "Notify User: Loaded X active alerts" or "MATCH FOUND").

### 4. Admin Bot
- [ ] Send `/start` to Admin Bot. -> Should show Admin Keyboard.
- [ ] Click "📊 Statistics". -> Should return stats.
