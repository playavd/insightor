# Manual Regression Checklist

Use this checklist to verify that the refactor has not introduced any regressions.

## 1. Startup & Stability
- [ ] **Start the Bot**: Run `python main.py`. Ensure no `ImportError` or immediate crash.
- [ ] **Logs**: Check `logs/insightor.log` for any initial errors.

## 2. Main Menu & Navigation
- [ ] **Menu Layout**: Send `/start` or `Menu` text. Verify expected buttons appear.
- [ ] **Navigation**: Click through "My Alerts", "Favorites", "Sellers" (if any). Ensure no crashes.

## 3. Favorites (Modified Module)
- [ ] **List Favorites**: Go to "Favorites". Ensure list loads correctly.
- [ ] **Pagination**: If you have >5 favorites, check Next/Prev buttons.
- [ ] **Details**: Click an ad in Favorites. Ensure details view loads with "Unfollow" and "Open on Site" buttons.
- [ ] **Add by URL (Success)**: 
    1. Click "Add by URL".
    2. Paste a valid Bazaraki ad URL (e.g., `https://www.bazaraki.com/adv/XXXXX/`).
    3. Verify it says "Ad Added" and returns to list.
- [ ] **Add by URL (Cancel)**:
    1. Click "Add by URL".
    2. Type `/cancel`.
    3. **Verify it returns to Favorites list without error.** (This was the fixed bug).

## 4. Scraper Cycle (Logic Refactor)
- [ ] **Run Cycle**: Wait for the scheduled scraper run (every 6 mins) or trigger manually if possible.
- [ ] **New Ads**: Create a broad alert (e.g., "Any Car < 100000"). Ensure new ads are detected and sent.
- [ ] **Price Updates**: If possible, modify a DB price entry manually and wait for next cycle to see if it detects change.
- [ ] **Notifications**: Ensure notifications still look correct (HTML parsing not broken).

## 5. Admin Functionality
- [ ] **Admin Notify**: Ensure the "Scraper cycle started..." message is received by Admin channel/ID.
