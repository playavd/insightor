# Refactor Changelog (2026-01-08)

## Overview
This refactor focused on cleaning up technical debt, removing dead code, and standardizing imports without altering the external behavior of the bot.

## Changes

### 1. **Code Cleanup / Dead Code Removal**
- **`scraper_service/logic.py`**:
  - Removed commented-out logic for ancient business detection rules (e.g., "Check for 'Show all ads' link").
  - Removed deprecated comments referencing moved code (e.g., `rescan_colors moved to maintenance.py`).
  - Removed redundant comments that just repeated code.

### 2. **Structural Improvements**
- **Import Standardization**:
  - Moved local imports to top-level in `main.py`, `scraper_service/logic.py`, and `client_bot/handlers/favorites.py`. This improves readability and prevents potential hidden circular dependency issues, as well as making dependencies explicit.
  - Affected files: `main.py`, `client_bot/handlers/favorites.py`, `scraper_service/logic.py`.

### 3. **Error Handling & Type Safety**
- **`scraper_service/logic.py`**:
  - Replaced silent `try...except: pass` blocks with `logger.warning()` or `logger.debug()` to ensure visibility of failures (e.g., price parsing failures).
- **`client_bot/handlers/favorites.py`**:
  - **Critical Fix**: Fixed a type error in `process_fav_url_input` where `show_favorites_page` was called with an `int` (`user_id`) as the first argument instead of a `Message` object. This would have caused a runtime error when trying to navigate back from an invalid URL input.

### 4. **2026-01-09 Refactor Logic Cleanup**
- **Duplication Removal**:
  - `scraper_service/logic.py`: Extracted `_extract_price` and `_detect_business_status` helper methods to remove duplicated logic found in listing parsing, detail parsing, and follow checks.
  - `shared/utils.py`: Extracted `get_status_display` to handle VIP/TOP label formatting in one place.
- **Complexity Reduction**:
  - `main.py`: Decomposed `notify_user` and `scraper_job` into smaller helper functions (`_notify_admin`, `_notify_matching_users`, `process_follow_notifications`).
- **Code Cleanliness**:
  - `client_bot/handlers/dashboard.py`: Removed inline imports, moving them to module level.
  - `shared/database.py`: Improved imports and type hinting.

### 5. **2026-01-09 Hotfix: Alert Notification Bug**
- **Bug**: Alerts with special characters (e.g., `<` in `<100k`) caused Telegram `Bad Request: can't parse entities`.
- **Fix**: Added `html.escape(alert['name'])` in `main.py` before constructing the notification message.

### 6. **2026-01-09 Hotfix: Management Bug**
- **Bug**: Similar to `main.py`, `client_bot/handlers/management.py` also injected `alert['name']` unsafely when Activating an alert.
- **Fix**: Applied `html.escape(alert['name'])` properly in the management handler.

## Behavior Consistency
- No changes were made to filter logic, DB schema, Telegram message formats, or user workflows.
- The scraper's request delays and anti-detection mechanisms remain untouched.
