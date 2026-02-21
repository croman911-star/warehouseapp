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
# This connects securely using the keys in your Streamlit Secrets vault
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    # Read the data from "Sheet1" (ttl=0 ensures it grabs live, fresh data)
    df_log = conn.read(worksheet="Sheet1", ttl=0)
    
    # If the sheet is totally blank, create our basic columns
    if len(df_log.columns) == 0 or "Model" not in df_log.columns:
        df_log = pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
except Exception as e:
    st.error("⚠️ Could not connect to Google Sheets. Please verify your Streamlit Secrets!")
    st.error(f"Error Summary: {repr(e)}")
    with st.expander("🔍 See Full Technical Error (Copy this for me!)"):
        st.code(traceback.format_exc())
    st.stop()

# --- Header ---
st.title("📦 Warehouse Inventory")
st.markdown("---")

# --- Input Area (Mobile Optimized) ---
# 1. Settings go first (since they usually stay the same for multiple entries)
colA, colB = st.columns(2)
with colA:
    loc = st.selectbox("Location", ["Warehouse", "Assembly", "Suspect"])
with colB:
    qty = st.number_input("Quantity", min_value=1, step=1, value=1)

st.markdown("<br>", unsafe_allow_html=True) # Adds a little spacing

# 2. Model input is grouped directly above the Action buttons for easy thumb access
model = st.text_input("Model Number ⬇️", placeholder="Type or scan model...").upper().strip()

# --- Math & Database Functions ---
def modify_inventory(direction):
    if not model:
        st.error("Please enter a Model Number.")
        return
        
    change = qty if direction == "add" else -qty
    action_word = "Added" if direction == "add" else "Removed"
    
    # Create the new log entry
    new_row = pd.DataFrame([{
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Action": action_word,
        "Model": model,
        "Location": loc,
        "Quantity": change
    }])
    
    # Add it to the bottom of our existing data
    updated_df = pd.concat([df_log, new_row], ignore_index=True)
    
    # Save the updated ledger back to Google Sheets
    with st.spinner("Saving to Google Sheets..."):
        conn.update(worksheet="Sheet1", data=updated_df)
        st.cache_data.clear() # Clear memory so it refreshes perfectly
        st.rerun()

def undo_last():
    if df_log.empty:
        st.warning("Nothing to undo!")
        return
        
    # Delete the very last row in the dataframe to undo it
    updated_df = df_log.iloc[:-1]
    
    with st.spinner("Undoing last action..."):
        conn.update(worksheet="Sheet1", data=updated_df)
        st.cache_data.clear()
        st.rerun()

# --- Action Buttons ---
# 3. Action buttons immediately follow the Model Number
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
    # This automatically groups identical models and calculates their totals!
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
    
    # Search Bar
    search = st.text_input("🔍 Search Models to Filter:")
    if search:
        df_display = df_display[df_display["Model"].str.contains(search.upper())]
        
    # Draw the table
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    
    # Excel Download Button
    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    csv = df_display.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 DOWNLOAD EXCEL",
        data=csv,
        file_name=f"Inventory_{now}.csv",
        mime="text/csv",
    )
else:
    st.info("List is empty. Add models above.")

# --- Hidden History Log ---
with st.expander("Show Recent History Log"):
    if not df_log.empty:
        # Show the last 10 entries in reverse order
        recent = df_log.tail(10).iloc[::-1]
        for _, row in recent.iterrows():
            st.text(f"[{row['Timestamp']}] {row['Action']} {abs(row['Quantity'])} x {row['Model']} ({row['Location']})")
    else:
        st.text("No history yet.")

# --- Reset Button ---
st.markdown("<br><br>", unsafe_allow_html=True)
if st.button("⚠️ Wipe Database (Clear All Data)"):
    # This overwrites the Google Sheet with a blank slate
    empty_df = pd.DataFrame(columns=["Timestamp", "Action", "Model", "Location", "Quantity"])
    with st.spinner("Wiping database..."):
        conn.update(worksheet="Sheet1", data=empty_df)
        st.cache_data.clear()
        st.rerun()
