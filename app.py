import streamlit as st
import pandas as pd
from datetime import datetime
import traceback
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

# --- QUOTA DEFENSE: Caching the Read ---
@st.cache_data(ttl=15)
def fetch_data():
    try:
        df = conn.read(worksheet="Sheet1")
        if len(df.columns) == 0 or "Model" not in df.columns:
            return pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
        return df
    except Exception as e:
        return e

data_result = fetch_data()

if isinstance(data_result, Exception):
    st.error("⚠️ Connection issues or Speed Limit reached.")
    st.info("Wait 30-60 seconds and refresh the page.")
    st.stop()
else:
    df_log = data_result

# --- Header ---
st.title("📦 Warehouse Inventory")
st.markdown("---")

# --- Math & Database Functions with Automatic Retry ---
def safe_update(dataframe):
    """Retries the update 3 times with a backoff to beat the quota limit."""
    for attempt in range(3):
        try:
            conn.update(worksheet="Sheet1", data=dataframe)
            return True
        except Exception as e:
            if "429" in str(e) or "Quota" in str(e):
                time.sleep(2) # Wait 2 seconds before retrying
                continue
            else:
                raise e
    return False

# --- STICKY LOCATION (Outside the form so it doesn't reset) ---
# This ensures that once you pick your area, it stays there until you manually change it.
loc = st.selectbox("📍 Current Location", ["Warehouse", "Assembly", "Suspect"])

st.markdown("<br>", unsafe_allow_html=True)

# --- INPUT FORM (The Disciplined Stance) ---
with st.form("inventory_form", clear_on_submit=True):
    # Quantity is now in its own row inside the form
    qty = st.number_input("Quantity", min_value=1, step=1, value=1)

    # Model Selection Logic
    existing_models = []
    if not df_log.empty and "Model" in df_log.columns:
        existing_models = sorted(df_log['Model'].dropna().unique().tolist())

    options = ["-- Type/Scan New Model Below --"] + existing_models if existing_models else ["-- Type/Scan New Model Below --"]

    model_selected = st.selectbox("📋 Quick Select Existing Model:", options)
    model_typed = st.text_input("⌨️ Type or Scan Model ⬇️", placeholder="Type or scan model...").upper().strip()

    # Resolve active model
    if model_typed:
        active_model = model_typed
    elif model_selected != "-- Type/Scan New Model Below --":
        active_model = model_selected
    else:
        active_model = ""

    # Action Buttons inside the Form
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        add_btn = st.form_submit_button("ADD (+)", use_container_width=True, type="primary")
    with f_col2:
        sub_btn = st.form_submit_button("SUB (-)", use_container_width=True)

    if add_btn or sub_btn:
        if not active_model:
            st.error("Please enter a Model Number.")
        else:
            direction = "add" if add_btn else "sub"
            change = qty if direction == "add" else -qty
            action_word = "Added" if direction == "add" else "Removed"
            
            new_row = pd.DataFrame([{
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Action": action_word,
                "Model": active_model,
                "Location": loc,
                "Quantity": change
            }])
            
            updated_df = pd.concat([df_log, new_row], ignore_index=True)
            
            with st.spinner("Saving..."):
                if safe_update(updated_df):
                    st.cache_data.clear()
                    st.success(f"✓ {action_word} {qty} {active_model} at {loc}")
                    time.sleep(1) 
                    st.rerun()
                else:
                    st.error("Google's speed limit is active. Wait 1 min.")

# --- Undo Button (Outside the form) ---
if st.button("↺ Undo Last Entry", use_container_width=True):
    if df_log.empty:
        st.warning("Nothing to undo!")
    else:
        updated_df = df_log.iloc[:-1]
        with st.spinner("Undoing..."):
            if safe_update(updated_df):
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Could not undo. Speed limit active.")

st.markdown("---")

# --- Live Report Area ---
st.subheader("📊 Live List")

report_rows = []
if not df_log.empty:
    summary = df_log.groupby(['Model', 'Location'])['Quantity'].sum().reset_index()
    unique_models = sorted(summary['Model'].unique())
    
    for m in unique_models:
        model_data = summary[summary['Model'] == m]
        wh = model_data[model_data['Location'] == 'Warehouse']['Quantity'].sum()
        asm = model_data[model_data['Location'] == 'Assembly']['Quantity'].sum()
        susp = model_data[model_data['Location'] == 'Suspect']['Quantity'].sum()
        total = wh + asm
        
        if total != 0 or susp != 0:
            report_rows.append({
                "Model": m, "Warehouse": int(wh), "Assembly": int(asm), "Total": int(total), "Suspect": int(susp)
            })

if report_rows:
    df_display = pd.DataFrame(report_rows)
    search = st.text_input("🔍 Filter List:")
    if search:
        df_display = df_display[df_display["Model"].str.contains(search.upper())]
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    
    csv = df_display.to_csv(index=False).encode('utf-8')
    st.download_button(label="📥 DOWNLOAD EXCEL", data=csv, file_name=f"Inventory_{datetime.now().strftime('%H%M')}.csv", mime="text/csv")
else:
    st.info("List is empty.")

# --- History Log ---
with st.expander("Show History"):
    if not df_log.empty:
        recent = df_log.tail(10).iloc[::-1]
        for _, row in recent.iterrows():
            st.text(f"[{row['Timestamp']}] {row['Action']} {abs(row['Quantity'])} x {row['Model']} ({row['Location']})")

# --- Reset Button ---
st.markdown("<br>", unsafe_allow_html=True)
if st.button("⚠️ Wipe Database"):
    empty_df = pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
    if safe_update(empty_df):
        st.cache_data.clear()
        st.rerun()
