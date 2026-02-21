import streamlit as st
import pandas as pd
from datetime import datetime
import time
from streamlit_gsheets import GSheetsConnection

# --- Page Setup ---
st.set_page_config(page_title="Warehouse Inventory", page_icon="📦", layout="centered")

# --- Authentication (The Bouncer) ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 App Locked")
    st.warning("Please enter the password to access the inventory.")
    
    pwd = st.text_input("Password", type="password")
    
    if st.button("Login"):
        correct_password = st.secrets.get("app_password", "blackbelt")
        if pwd == correct_password: 
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password. Access Denied.")
    st.stop() 

# --- Database Connection (Google Sheets) ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- OPTIMIZED DATA FETCHING ---
@st.cache_data(ttl=60) # Longer cache for general views
def fetch_data():
    try:
        df = conn.read(worksheet="Sheet1")
        if df is None or not isinstance(df, pd.DataFrame):
            return pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
        if "Model" not in df.columns:
            return pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
        # Clean data: Ensure Quantity is numeric and Model is string
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0)
        df['Model'] = df['Model'].astype(str).str.upper().str.strip()
        return df
    except Exception as e:
        return str(e)

# Initialize page data
data_result = fetch_data()

if isinstance(data_result, str):
    st.error("⚠️ The dojo is currently busy (Google Speed Limit).")
    st.info("Wait 30 seconds for the system to regain its balance and refresh.")
    with st.expander("Technical Stance Details"):
        st.write(data_result)
    st.stop()
else:
    df_log = data_result

# --- Math & Database Functions ---
def safe_update(dataframe):
    """Retries the update with exponential backoff to maximize success chance."""
    wait_times = [1, 2, 4] # Wait 1s, then 2s, then 4s if blocked
    for attempt, wait in enumerate(wait_times):
        try:
            conn.update(worksheet="Sheet1", data=dataframe)
            return True
        except Exception as e:
            if "429" in str(e) or "Quota" in str(e):
                if attempt < len(wait_times) - 1:
                    time.sleep(wait)
                    continue
            st.error(f"Strike failed: {str(e)}")
            return False
    return False

# --- Header ---
st.title("📦 Warehouse Inventory")
st.markdown("---")

# --- STICKY LOCATION ---
loc = st.selectbox("📍 Current Location", ["Warehouse", "Assembly", "Suspect"])

# --- INPUT FORM ---
with st.form("inventory_form", clear_on_submit=True):
    qty = st.number_input("Quantity", min_value=1, step=1, value=1)

    # Robust Model Selection
    existing_models = []
    if not df_log.empty:
        models_list = df_log['Model'].unique().tolist()
        existing_models = sorted([m for m in models_list if m and m != 'NAN'])

    options = ["-- Type/Scan New Model Below --"] + existing_models
    model_selected = st.selectbox("📋 Quick Select Existing Model:", options)
    model_typed = st.text_input("⌨️ Type or Scan Model ⬇️", placeholder="Type or scan model...").upper().strip()

    active_model = model_typed if model_typed else (model_selected if model_selected != "-- Type/Scan New Model Below --" else "")

    col1, col2 = st.columns(2)
    with col1:
        add_btn = st.form_submit_button("ADD (+)", use_container_width=True, type="primary")
    with col2:
        sub_btn = st.form_submit_button("SUB (-)", use_container_width=True)

    if add_btn or sub_btn:
        if not active_model:
            st.error("Missing Model: Please specify what you are moving.")
        else:
            direction = "add" if add_btn else "sub"
            change = qty if direction == "add" else -qty
            
            new_row = pd.DataFrame([{
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Action": "Added" if add_btn else "Removed",
                "Model": active_model,
                "Location": loc,
                "Quantity": change
            }])
            
            updated_df = pd.concat([df_log, new_row], ignore_index=True)
            
            with st.spinner("Logging transaction..."):
                if safe_update(updated_df):
                    st.cache_data.clear() # Immediate clear so the view is fresh
                    st.success(f"✓ Recorded: {qty} units of {active_model}")
                    time.sleep(0.5)
                    st.rerun()

# --- Utility Buttons ---
if st.button("↺ Undo Last Entry", use_container_width=True):
    if df_log.empty:
        st.warning("History is empty.")
    else:
        updated_df = df_log.iloc[:-1]
        if safe_update(updated_df):
            st.cache_data.clear()
            st.rerun()

st.markdown("---")

# --- LIVE REPORT AREA ---
st.subheader("📊 Live Stock Status")

if not df_log.empty:
    # Efficiently aggregate totals
    summary = df_log.groupby(['Model', 'Location'])['Quantity'].sum().unstack(fill_value=0).reset_index()
    
    # Ensure all columns exist for a consistent UI
    for c in ["Warehouse", "Assembly", "Suspect"]:
        if c not in summary.columns:
            summary[c] = 0
            
    summary['Total'] = summary['Warehouse'] + summary['Assembly']
    
    # Search/Filter
    search = st.text_input("🔍 Quick Search Models:")
    if search:
        summary = summary[summary["Model"].str.contains(search.upper())]
    
    st.dataframe(
        summary[["Model", "Warehouse", "Assembly", "Total", "Suspect"]].sort_values("Model"),
        use_container_width=True,
        hide_index=True
    )
    
    # Download
    csv = summary.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Export CSV", data=csv, file_name=f"stock_{datetime.now().strftime('%m%d')}.csv", mime="text/csv")
else:
    st.info("No items in the database.")

with st.expander("📝 View Recent Logs"):
    if not df_log.empty:
        st.dataframe(df_log.tail(15).iloc[::-1], use_container_width=True, hide_index=True)

# --- Wipe Database ---
st.markdown("<br><br>", unsafe_allow_html=True)
if st.button("⚠️ Emergency: Wipe All Data"):
    empty_df = pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
    if safe_update(empty_df):
        st.cache_data.clear()
        st.rerun()

