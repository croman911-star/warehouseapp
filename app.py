import streamlit as st
import pandas as pd
from datetime import datetime
import json
import os
import glob

# --- Page Setup ---
st.set_page_config(page_title="Warehouse Inventory", page_icon="📦", layout="centered")

# --- USER ACCOUNTS ---
# Add or remove users here. Format is "Username": "Password"
USERS = {
    "Admin": "copper713",
    "Cesar": "copper123", 
    "Daniel": "copper1",
    "Worker2": "pass2"
}

# --- Authentication Logic ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'current_user' not in st.session_state:
    st.session_state.current_user = None

if not st.session_state.authenticated:
    st.title("🔒 Warehouse Login")
    st.markdown("Please log in to access your personal inventory workspace.")
    
    # Login Form
    username_guess = st.text_input("Username")
    pwd_guess = st.text_input("Password", type="password")
    
    if st.button("Login", type="primary"):
        # Check if the username exists and the password matches
        if username_guess in USERS and USERS[username_guess] == pwd_guess:
            st.session_state.authenticated = True
            st.session_state.current_user = username_guess
            st.rerun()
        else:
            st.error("Incorrect username or password.")
            
    # Stop the rest of the app from loading until logged in
    st.stop()

# ==========================================
# IF AUTHENTICATED, RUN THE REST OF THE APP
# ==========================================

# --- Local Database Configuration (Now User-Specific!) ---
def get_data_file():
    # Creates a unique file for each user, e.g., "inventory_data_Admin.json"
    return f"inventory_data_{st.session_state.current_user}.json"

def get_hist_file():
    return f"inventory_history_{st.session_state.current_user}.json"

def load_local_db():
    data_file = get_data_file()
    hist_file = get_hist_file()
    
    if 'data' not in st.session_state:
        if os.path.exists(data_file):
            with open(data_file, 'r') as f:
                st.session_state.data = json.load(f)
        else:
            st.session_state.data = {}

    if 'history' not in st.session_state:
        if os.path.exists(hist_file):
            with open(hist_file, 'r') as f:
                st.session_state.history = json.load(f)
        else:
            st.session_state.history = []

def save_local_db():
    data_file = get_data_file()
    hist_file = get_hist_file()
    
    with open(data_file, 'w') as f:
        json.dump(st.session_state.data, f)
    with open(hist_file, 'w') as f:
        json.dump(st.session_state.history, f)

# Initialize the database on startup for the logged-in user
load_local_db()

# --- Header ---
colA, colB = st.columns([4, 1])
with colA:
    st.title(f"📦 Workspace: {st.session_state.current_user}")
with colB:
    if st.button("Logout", key="logout_btn"):
        # Clear the session when logging out
        st.session_state.authenticated = False
        st.session_state.current_user = None
        # Remove data from session memory so next user doesn't see it before load
        if 'data' in st.session_state: del st.session_state.data
        if 'history' in st.session_state: del st.session_state.history
        st.rerun()

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
            save_local_db() # Save the undo action
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
        # Adds the username to the Excel file so you know whose count it is!
        file_name=f"Inventory_{st.session_state.current_user}_{now}.csv",
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
        save_local_db()
        st.rerun()

with reset_col2:
    if st.button("🗑️ Wipe Everything (Hard Reset)", use_container_width=True):
        st.session_state.data = {}
        st.session_state.history = []
        save_local_db() 
        st.rerun()

# --- ADMIN MASTER VIEW ---
if st.session_state.current_user == "Admin":
    st.markdown("---")
    st.header("👑 Admin Master Dashboard")
    st.write("Aggregated totals combined from all users' personal workspaces.")
    
    master_data = {}
    # The Admin code sweeps the folder to find EVERY user's saved data file
    for file in glob.glob("inventory_data_*.json"):
        with open(file, "r") as f:
            try:
                user_data = json.load(f)
                for k, v in user_data.items():
                    # Combine the counts from all users
                    master_data[k] = master_data.get(k, 0) + v
            except:
                pass
                
    master_rows = []
    master_models = sorted(list(set([k.split("|")[0] for k in master_data.keys()])))
    
    for m in master_models:
        wh = master_data.get(f"{m}|Warehouse", 0)
        asm = master_data.get(f"{m}|Assembly", 0)
        susp = master_data.get(f"{m}|Suspect", 0)
        total = wh + asm
        
        if total != 0 or susp != 0:
            master_rows.append({
                "Model": m, 
                "Warehouse": wh, 
                "Assembly": asm, 
                "Total": total, 
                "Suspect (Bad)": susp
            })
            
    if master_rows:
        df_master = pd.DataFrame(master_rows)
        st.dataframe(df_master, use_container_width=True, hide_index=True)
        
        now = datetime.now().strftime("%Y-%m-%d_%H-%M")
        csv_master = df_master.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 DOWNLOAD MASTER EXCEL (ALL USERS)",
            data=csv_master,
            file_name=f"Inventory_MASTER_{now}.csv",
            mime="text/csv",
            type="primary" # Makes the Admin download button stand out
        )
    else:
        st.info("No data across any users yet.")
