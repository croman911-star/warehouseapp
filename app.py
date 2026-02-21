import streamlit as st
import pandas as pd
from datetime import datetime
import traceback
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
@st.cache_data(ttl=10)
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
    st.error("⚠️ Connection issues. Please wait 60 seconds.")
    st.stop()
else:
    df_log = data_result

# --- Form Reset Logic (The Ready Stance) ---
def reset_form():
    st.session_state.qty_input = 1
    st.session_state.text_input = ""
    st.session_state.select_input = "-- Type/Scan New Model Below --"

# Initialize state keys if they don't exist
if "qty_input" not in st.session_state:
    st.session_state.qty_input = 1
if "text_input" not in st.session_state:
    st.session_state.text_input = ""
if "select_input" not in st.session_state:
    st.session_state.select_input = "-- Type/Scan New Model Below --"

# --- Header ---
st.title("📦 Warehouse Inventory")
st.markdown("---")

# --- Input Area (Mobile Optimized) ---
colA, colB = st.columns(2)
with colA:
    loc = st.selectbox("Location", ["Warehouse", "Assembly", "Suspect"])
with colB:
    qty = st.number_input("Quantity", min_value=1, step=1, key="qty_input")

st.markdown("<br>", unsafe_allow_html=True)

# --- Model Selection Logic ---
existing_models = []
if not df_log.empty and "Model" in df_log.columns:
    existing_models = sorted(df_log['Model'].dropna().unique().tolist())

options = ["-- Type/Scan New Model Below --"] + existing_models if existing_models else ["-- Type/Scan New Model Below --"]

# 1. Quick Select
model_selected = st.selectbox(
    "📋 Quick Select Existing Model:", 
    options,
    key="select_input"
)

# 2. Text Input
model_typed = st.text_input(
    "⌨️ Type or Scan Model ⬇️", 
    placeholder="Type or scan model...",
    key="text_input"
).upper().strip()

# Resolve active model: Typed text overrides selection if present
if model_typed:
    active_model = model_typed
elif model_selected != "-- Type/Scan New Model Below --":
    active_model = model_selected
else:
    active_model = ""

# --- Math & Database Functions ---
def modify_inventory(direction):
    if not active_model:
        st.error("Please enter a Model Number.")
        return
        
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
    
    with st.spinner("Saving to Google Sheets..."):
        try:
            conn.update(worksheet="Sheet1", data=updated_df)
            st.cache_data.clear() # Clear cache to show new data immediately
            reset_form() # Reset the fields for the next entry
            st.rerun()
        except Exception as e:
            st.error("Save failed. You may have hit the Google speed limit. Wait 1 min.")

def undo_last():
    if df_log.empty:
        st.warning("Nothing to undo!")
        return
    updated_df = df_log.iloc[:-1]
    with st.spinner("Undoing..."):
        conn.update(worksheet="Sheet1", data=updated_df)
        st.cache_data.clear()
        reset_form()
        st.rerun()

# --- Action Buttons ---
btn_col1, btn_col2, btn_col3 = st.columns(3)
with btn_col1:
    if st.button("ADD (+)", use_container_width=True, type="primary"):
        modify_inventory("add")
with btn_col2:
    if st.button("SUB (-)", use_container_width=True):
        modify_inventory("sub")
with btn_col3:
    if st.button("↺ Undo", use_container_width=True):
        undo_last()

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
            st.text(f"[{row['Timestamp']}] {row['Action']} {abs(row['Quantity'])} x {row['Model']}")

# --- Reset Button ---
st.markdown("<br>", unsafe_allow_html=True)
if st.button("⚠️ Wipe Database"):
    empty_df = pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
    conn.update(worksheet="Sheet1", data=empty_df)
    st.cache_data.clear()
    reset_form()
    st.rerun()
