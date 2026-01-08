from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

def get_main_menu_kb(alerts_count: int = 0, favorites_count: int = 0):
    buttons = []
    
    # 1. New Alert vs My Alerts
    if alerts_count == 0:
        buttons.append(KeyboardButton(text="🔔 New Alert"))
    else:
        buttons.append(KeyboardButton(text="🗂️ My Alerts"))
    
    # 2. Favorites
    if favorites_count > 0:
        buttons.append(KeyboardButton(text="⭐ Favorites"))
    
    # 3. Archive
    buttons.append(KeyboardButton(text="🔍 Archive"))
    
    # 4. Pro
    buttons.append(KeyboardButton(text="⭐ Pro"))

    # Chunk into rows of 2
    keyboard = []
    row = []
    for btn in buttons:
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_nav_kb(options: list[str] | None = None, include_any: bool = True):
    """
    Helper to create keyboards dynamically.
    options: List of main option buttons (e.g. ["Automatic", "Manual"])
    """
    kb = []
    if options:
        # Group options into rows of 2 or 3
        row = []
        for opt in options:
            row.append(KeyboardButton(text=opt))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
    
    if include_any:
        kb.insert(0, [KeyboardButton(text="ANY")])

    # Control Row
    control_row = [
        KeyboardButton(text="⬅️ Back"),
        KeyboardButton(text="💾 Save & Finish"),
        KeyboardButton(text="❌ Cancel")
    ]
    kb.append(control_row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_dashboard_kb(filters: dict) -> InlineKeyboardMarkup:
    """
    Generates the Main Dashboard Inline Keyboard based on current filters.
    """
    builder = InlineKeyboardBuilder()

    # Helper to format button text
    def fmt(label, key, suffix="", prefix=""):
        val = filters.get(key)
        if val is None: return f"{label}: Any"
        return f"{label}: {prefix}{val}{suffix}"

    # Row 1: Brand & Model
    builder.button(text=fmt("Brand", "brand"), callback_data="edit_brand")
    # Show Model ONLY if Brand is selected
    if filters.get("brand"):
        builder.button(text=fmt("Model", "model"), callback_data="edit_model")
    
    # Row 2: Year (Min & Max)
    # Year Max only visible if Year Min is set
    builder.button(text=fmt("Year min", "year_min", prefix=">"), callback_data="edit_year_min")
    if filters.get("year_min"):
        builder.button(text=fmt("Year max", "year_max", prefix="<"), callback_data="edit_year_max")
    
    # Row 3: Price (Max & Min)
    # Price Min visible regardless
    builder.button(text=fmt("Price max", "price_max", "€", prefix="<"), callback_data="edit_price_max")
    builder.button(text=fmt("Price min", "price_min", "€", prefix=">"), callback_data="edit_price_min")

    # Row 4: Mileage
    builder.button(text=fmt("Mileage", "mileage_max", " km", prefix="<"), callback_data="edit_mileage_max")
    
    # Row 5: Engine (Min & Max visible regardless)
    builder.button(text=fmt("Engine min", "engine_min", " cc", prefix=">"), callback_data="edit_engine_min")
    builder.button(text=fmt("Engine max", "engine_max", " cc", prefix="<"), callback_data="edit_engine_max")
    
    # Row 6: Gearbox & Fuel
    builder.button(text=fmt("Gearbox", "gearbox"), callback_data="edit_gearbox")
    builder.button(text=fmt("Fuel", "fuel_type"), callback_data="edit_fuel_type")

    # Row 7: Drivetrain & Body
    builder.button(text=fmt("Drivetrain", "drive_type"), callback_data="edit_drive_type")
    builder.button(text=fmt("Body", "body_type"), callback_data="edit_body_type")
    
    # Row 8: Color
    builder.button(text=fmt("Color", "color"), callback_data="edit_color")
    
    # Row 9: Promo (Ad Status)
    builder.button(text=fmt("Promo", "ad_status"), callback_data="edit_ad_status")

    # Row 10: Seller Type & ID
    u_type = filters.get('is_business')
    u_label = "Any"
    if u_type is True: u_label = "Business"
    elif u_type is False: u_label = "Private"
    builder.button(text=f"Seller Type: {u_label}", callback_data="edit_is_business")
    
    builder.button(text=fmt("Seller ID", "target_user_id"), callback_data="edit_target_user_id")

    sizes = []
    # R1
    sizes.append(2 if filters.get("brand") else 1)
    # R2
    sizes.append(2 if filters.get("year_min") else 1)
    # R3 (Price)
    sizes.append(2)
    # R4 (Mileage)
    sizes.append(1)
    # R5 (Engine)
    sizes.append(2)
    # R6 (Gearbox/Fuel)
    sizes.append(2)
    # R7 (Drive/Body)
    sizes.append(2)
    # R8 (Color)
    sizes.append(1)
    # R9 (Promo)
    sizes.append(1)
    # R10 (Seller)
    sizes.append(2)
    
    builder.adjust(*sizes)
    
    builder.row(
        InlineKeyboardButton(text="🔙 Back", callback_data="dash_cancel"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="dash_cancel"),
        InlineKeyboardButton(text="✅ Activate", callback_data="dash_save")
    )
    
    return builder.as_markup()
