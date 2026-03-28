import streamlit as st
import pandas as pd
from datetime import datetime
import json
import os

# --- Page Setup ---
st.set_page_config(page_title="Warehouse Inventory", page_icon="📦", layout="centered")

# --- Local Database Configuration ---
DATA_FILE = "inventory_data.json"
HIST_FILE = "inventory_history.json"

def load_local_db():
    if 'data' not in st.session_state:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                st.session_state.data = json.load(f)
        else:
            st.session_state.data = {}

    if 'history' not in st.session_state:
        if os.path.exists(HIST_FILE):
            with open(HIST_FILE, 'r') as f:
                st.session_state.history = json.load(f)
        else:
            st.session_state.history = []

def save_local_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(st.session_state.data, f)
    with open(HIST_FILE, 'w') as f:
        json.dump(st.session_state.history, f)

# Initialize the database on startup
load_local_db()

# --- Header ---
st.title("📦 Warehouse Inventory")
st.markdown("---")

# Extract all known models for our dropdown
unique_models = sorted(list(set([k.split("|")[0] for k in st.session_state.data.keys()])))

# --- Input Area ---
st.write("**Add / Remove Inventory**")
col1, col2 = st.columns([2, 2])

with col1:
    if unique_models:
        options = ["-- Select Existing Model --", "+ ADD NEW MODEL"] + unique_models
        model_choice = st.selectbox("Model Selection", options)
        if model_choice == "+ ADD NEW MODEL" or model_choice == "-- Select Existing Model --":
            model = st.text_input("Type New Model Number").upper().strip()
        else:
            model = model_choice
    else:
        model = st.text_input("Model Number").upper().strip()

with col2:
    qty = st.number_input("Quantity", min_value=1, step=1, value=1)
    loc = st.selectbox("Location", ["Warehouse", "Assembly", "Suspect"])

# --- Math & Logic Functions ---
def modify_inventory(direction):
    if not model:
        st.error("Please select or enter a Model Number.")
        return
        
    key = f"{model}|{loc}"
    if key not in st.session_state.data:
        st.session_state.data[key] = 0
        
    change = qty if direction == "add" else -qty
    st.session_state.data[key] += change
    
    action_word = "Added" if direction == "add" else "Removed"
    st.session_state.history.append({
        "action": action_word,
        "model": model,
        "qty": qty,
        "loc": loc,
        "key": key,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })
    
    # Save to the hard drive immediately
    save_local_db()
    
    if direction == "add":
        st.success(f"✓ {action_word} {qty} {model} ({loc}) [Total: {st.session_state.data[key]}]")
    else:
        st.warning(f"⚠ {action_word} {qty} {model} ({loc}) [Total: {st.session_state.data[key]}]")

# --- Action Buttons ---
btn_col1, btn_col2, btn_col3 = st.columns(3)
with btn_col1:
    if st.button("ADD (+)", use_container_width=True, type="primary"):
        modify_inventory("add")
        st.rerun() 
with btn_col2:
    if st.button("SUB (-)", use_container_width=True):
        modify_inventory("sub")
        st.rerun()
with btn_col3:
    if st.button("↺ Undo Last", use_container_width=True):
        if not st.session_state.history:
            st.warning("Nothing to undo!")
        else:
            last = st.session_state.history.pop()
            change = last["qty"] if last["action"] == "Added" else -last["qty"]
            st.session_state.data[last["key"]] -= change
            save_local_db() # Save the undo action to hard drive
            st.info(f"↺ Undid last action for {last['model']}")
            st.rerun()

st.markdown("---")

# --- Live Report Area ---
st.subheader("📊 Live List (In Stock Only)")

report_rows = []

for m in unique_models:
    wh = st.session_state.data.get(f"{m}|Warehouse", 0)
    asm = st.session_state.data.get(f"{m}|Assembly", 0)
    susp = st.session_state.data.get(f"{m}|Suspect", 0)
    total = wh + asm
    
    if total != 0 or susp != 0:
        report_rows.append({
            "Model": m, 
            "Warehouse": wh, 
            "Assembly": asm, 
            "Total": total, 
            "Suspect (Bad)": susp
        })

if report_rows:
    df = pd.DataFrame(report_rows)
    
    search = st.text_input("🔍 Search Models to Filter:")
    if search:
        df = df[df["Model"].str.contains(search.upper())]
        
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 DOWNLOAD EXCEL",
        data=csv,
        file_name=f"Inventory_{now}.csv",
        mime="text/csv",
    )
else:
    st.info("No items currently in stock. Add items above.")

with st.expander("Show Recent History Log"):
    if st.session_state.history:
        for item in reversed(st.session_state.history[-10:]):
            st.text(f"[{item['timestamp']}] {item['action']} {item['qty']} x {item['model']} ({item['loc']})")
    else:
        st.text("No history yet.")

# --- System Management ---
st.markdown("<br><br>", unsafe_allow_html=True)
st.subheader("⚙️ System Management")

reset_col1, reset_col2 = st.columns(2)

with reset_col1:
    if st.button("🔄 Reset Counts to 0 (Keep Memory)", use_container_width=True):
        for key in st.session_state.data:
            st.session_state.data[key] = 0
        st.session_state.history = []  
        save_local_db() # Clear local files too
        st.rerun()

with reset_col2:
    if st.button("🗑️ Wipe Everything (Hard Reset)", use_container_width=True):
        st.session_state.data = {}
        st.session_state.history = []
        save_local_db() # Wipe local files
        st.rerun()
