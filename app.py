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

try:
    df_log = conn.read(worksheet="Sheet1", ttl=0)
    if len(df_log.columns) == 0 or "Model" not in df_log.columns:
        df_log = pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
except Exception as e:
    st.error("⚠️ Could not connect to Google Sheets. Please verify your Streamlit Secrets!")
    st.error(f"Error Summary: {repr(e)}")
    with st.expander("🔍 See Full Technical Error"):
        st.code(traceback.format_exc())
    st.stop()

# --- Initialize Proxy State ---
# This acts as our "Ready Stance" - holding the data outside the widgets
if "proxy_qty" not in st.session_state:
    st.session_state.proxy_qty = 1
if "proxy_model" not in st.session_state:
    st.session_state.proxy_model = ""
if "proxy_select" not in st.session_state:
    st.session_state.proxy_select = "-- Type/Scan New Model Below --"

# --- Header ---
st.title("📦 Warehouse Inventory")
st.markdown("---")

# --- Input Area (Mobile Optimized) ---
colA, colB = st.columns(2)
with colA:
    loc = st.selectbox("Location", ["Warehouse", "Assembly", "Suspect"])
with colB:
    # Use value= from our proxy state
    qty = st.number_input("Quantity", min_value=1, step=1, value=st.session_state.proxy_qty)
    st.session_state.proxy_qty = qty # Update proxy when changed

st.markdown("<br>", unsafe_allow_html=True)

# --- Model Selection Logic ---
existing_models = []
if not df_log.empty and "Model" in df_log.columns:
    existing_models = sorted(df_log['Model'].dropna().unique().tolist())

# Logic for clearing one box when the other is used
options = ["-- Type/Scan New Model Below --"] + existing_models if existing_models else ["-- Type/Scan New Model Below --"]

# 1. Quick Select
model_selected = st.selectbox(
    "📋 Quick Select Existing Model:", 
    options,
    index=options.index(st.session_state.proxy_select) if st.session_state.proxy_select in options else 0
)

# 2. Text Input
model_typed = st.text_input(
    "⌨️ Type or Scan Model ⬇️", 
    placeholder="Type or scan model...",
    value=st.session_state.proxy_model
).upper().strip()

# --- Interaction Logic (Hand-to-Hand synchronization) ---
if model_typed != st.session_state.proxy_model:
    # User typed something new! Reset the dropdown proxy
    st.session_state.proxy_model = model_typed
    st.session_state.proxy_select = "-- Type/Scan New Model Below --"
    st.rerun()

if model_selected != st.session_state.proxy_select:
    # User picked something from the list! Clear the text proxy
    st.session_state.proxy_select = model_selected
    st.session_state.proxy_model = ""
    st.rerun()

# Resolve final model choice
if st.session_state.proxy_select != "-- Type/Scan New Model Below --":
    active_model = st.session_state.proxy_select
else:
    active_model = st.session_state.proxy_model

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
        conn.update(worksheet="Sheet1", data=updated_df)
        st.cache_data.clear()
        
        # Reset Proxy State (The "Snap Back")
        st.session_state.proxy_qty = 1
        st.session_state.proxy_model = ""
        st.session_state.proxy_select = "-- Type/Scan New Model Below --"
        
        st.rerun()

def undo_last():
    if df_log.empty:
        st.warning("Nothing to undo!")
        return
    updated_df = df_log.iloc[:-1]
    with st.spinner("Undoing last action..."):
        conn.update(worksheet="Sheet1", data=updated_df)
        st.cache_data.clear()
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
    if st.button("↺ Undo Last", use_container_width=True):
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
                "Model": m, 
                "Warehouse": int(wh), 
                "Assembly": int(asm), 
                "Total": int(total), 
                "Suspect (Bad)": int(susp)
            })

if report_rows:
    df_display = pd.DataFrame(report_rows)
    search = st.text_input("🔍 Search Models to Filter:")
    if search:
        df_display = df_display[df_display["Model"].str.contains(search.upper())]
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    
    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    csv = df_display.to_csv(index=False).encode('utf-8')
    st.download_button(label="📥 DOWNLOAD EXCEL", data=csv, file_name=f"Inventory_{now}.csv", mime="text/csv")
else:
    st.info("List is empty. Add models above.")

# --- History Log ---
with st.expander("Show Recent History Log"):
    if not df_log.empty:
        recent = df_log.tail(10).iloc[::-1]
        for _, row in recent.iterrows():
            st.text(f"[{row['Timestamp']}] {row['Action']} {abs(row['Quantity'])} x {row['Model']} ({row['Location']})")
    else:
        st.text("No history yet.")

# --- Reset Button ---
st.markdown("<br><br>", unsafe_allow_html=True)
if st.button("⚠️ Wipe Database (Clear All Data)"):
    empty_df = pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
    with st.spinner("Wiping database..."):
        conn.update(worksheet="Sheet1", data=empty_df)
        st.cache_data.clear()
        st.rerun()
