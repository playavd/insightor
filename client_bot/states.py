from aiogram.fsm.state import State, StatesGroup

# --- FSM States ---
class AlertCreation(StatesGroup):
    # Category removed - hardcoded to Cars
    Brand = State()
    Model = State()
    YearFrom = State()
    YearTo = State()
    PriceMax = State()
    PriceMin = State() # Not in wizard flow usually but good to have
    MileageMax = State() 
    # Remaining fields populated via default or skipped in linear wizard?
    # Original wizard flow: Category -> Brand -> Model -> YearFrom -> YearTo -> PriceMax -> Save?
    # Actually checking original code:
    # process_brand -> ANY or Model
    # process_model -> YearFrom
    # process_year_from (implied?) -> YearTo
    # process_year_to -> PriceMax
    # process_price_max (implied?) -> Finish? 
    # The original code provided has process_brand, process_model, process_dashboard_text (generic), process_year_to.
    
    # We will keep these but just ensure we skip Category.
    
    # Generic states for specific step edits if we want strict flow, 
    # but mostly we use AlertEditor for complex edits.
    pass

class AlertEditor(StatesGroup):
    Menu = State()
    SelectBrand = State() # Maybe unused if replaced by generic SelectOption
    SelectModel = State() # Maybe unused if replaced by generic SelectOption
    SelectOption = State() # Generic option selector (Fuel, Body, etc.)
    InputText = State() # Generic text input (Year, Price, etc.)
    Rename = State() # Special state for renaming

class AlertManagement(StatesGroup):
    ViewingList = State()
    ViewingDetail = State()

class FavoriteAddition(StatesGroup):
    WaitingForURL = State()
