import streamlit as st
import pandas as pd
from datetime import datetime
import json
import os
import glob
import gspread

# --- Page Setup ---
st.set_page_config(page_title="Warehouse Inventory", page_icon="📦", layout="centered")

# --- USER ACCOUNTS ---
# Securely load passwords from Streamlit's hidden vault
try:
    USERS = st.secrets["passwords"]
except Exception:
    st.error("🚨 Security Alert: The hidden password vault is missing! Please set up your secrets.")
    st.stop()

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

# Extract ALL known models from ALL users for a Global Dropdown Dictionary
global_models = set()
# First, add current user's models
for k in st.session_state.data.keys():
    global_models.add(k.split("|")[0])
    
# Next, sweep all other users' files to build the master list of items
for file in glob.glob("inventory_data_*.json"):
    try:
        with open(file, "r") as f:
            user_data = json.load(f)
            for k in user_data.keys():
                global_models.add(k.split("|")[0])
    except:
        pass

unique_models = sorted(list(global_models))

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
    with st.expander("🔄 Reset Counts to 0"):
        if st.session_state.current_user == "Admin":
            st.warning("Are you sure? This sets ALL USERS' counts to 0 but keeps the models in memory.")
            if st.button("Yes, Reset All Counts", use_container_width=True):
                # 1. Reset Admin's current session
                for key in st.session_state.data:
                    st.session_state.data[key] = 0
                st.session_state.history = []
                save_local_db()
                
                # 2. Globally reset all other users' data files
                for file in glob.glob("inventory_data_*.json"):
                    try:
                        with open(file, "r") as f:
                            other_data = json.load(f)
                        for k in other_data:
                            other_data[k] = 0  # Set count to 0 but keep the model name
                        with open(file, "w") as f:
                            json.dump(other_data, f)
                    except:
                        pass
                        
                # 3. Globally clear all history logs for the new shift
                for file in glob.glob("inventory_history_*.json"):
                    try:
                        with open(file, "w") as f:
                            json.dump([], f)
                    except:
                        pass
                        
                st.rerun()
        else:
            st.warning("Are you sure? This sets all your personal counts to 0 but keeps the models in memory.")
            if st.button("Yes, Reset My Counts", use_container_width=True):
                for key in st.session_state.data:
                    st.session_state.data[key] = 0
                st.session_state.history = []  
                save_local_db()
                st.rerun()

with reset_col2:
    # Only Admin can see and use the Hard Reset
    if st.session_state.current_user == "Admin":
        with st.expander("🗑️ Wipe Everything"):
            st.warning("🚨 DANGER: This permanently erases all your models and counts. Are you sure?")
            if st.button("Yes, Wipe My Data", use_container_width=True, type="primary"):
                # 1. Clear the Admin's current screen
                st.session_state.data = {}
                st.session_state.history = []
                
                # 2. GLOBALLY wipe ALL user data files off the hard drive
                for file in glob.glob("inventory_data_*.json"):
                    try:
                        os.remove(file)
                    except:
                        pass
                        
                # 3. GLOBALLY wipe ALL user history files
                for file in glob.glob("inventory_history_*.json"):
                    try:
                        os.remove(file)
                    except:
                        pass
                
                # 4. Save a fresh empty state and reload
                save_local_db() 
                st.rerun()

st.markdown("---")

# Only Admin can delete models globally
if st.session_state.current_user == "Admin":
    with st.expander("❌ Delete a Specific Model (Fix Typos)"):
        st.write("Select a model to permanently remove from memory:")
        del_col1, del_col2 = st.columns([3, 1])
        with del_col1:
            model_to_delete = st.selectbox("Select model:", ["-- Select --"] + unique_models, label_visibility="collapsed")
        with del_col2:
            if st.button("Delete Model", use_container_width=True, type="primary"):
                if model_to_delete and model_to_delete != "-- Select --":
                    # 1. Delete from current user session
                    keys_to_delete = [k for k in st.session_state.data.keys() if k.startswith(f"{model_to_delete}|")]
                    for k in keys_to_delete:
                        del st.session_state.data[k]
                    save_local_db()
                    
                    # 2. Globally delete from ALL other users' files to completely purge the typo
                    for file in glob.glob("inventory_data_*.json"):
                        try:
                            with open(file, "r") as f:
                                other_data = json.load(f)
                            
                            changed = False
                            keys_to_purge = [k for k in other_data.keys() if k.startswith(f"{model_to_delete}|")]
                            for k in keys_to_purge:
                                del other_data[k]
                                changed = True
                                
                            if changed:
                                with open(file, "w") as f:
                                    json.dump(other_data, f)
                        except:
                            pass
                    
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
        
        # --- NEW: Side-by-Side Download & Sync Buttons ---
        col_dl, col_cloud = st.columns(2)
        
        with col_dl:
            st.download_button(
                label="📥 DOWNLOAD MASTER EXCEL",
                data=csv_master,
                file_name=f"Inventory_MASTER_{now}.csv",
                mime="text/csv",
                type="primary" 
            )
            
        with col_cloud:
            if st.button("☁️ Sync to Google Sheets", use_container_width=True):
                with st.spinner("Syncing to the Cloud..."):
                    try:
                        # 1. Connect to Google using our hidden vault
                        credentials = dict(st.secrets["gcp_service_account"])
                        gc = gspread.service_account_from_dict(credentials)
                        
                        # 2. Open the exact Google Sheet by its title
                        sh = gc.open("Warehouse Live Sync")
                        worksheet = sh.sheet1
                        
                        # 3. Wipe the old sheet data and paste the fresh Master List
                        worksheet.clear()
                        
                        # 4. Convert all data to plain text strings
                        data_to_upload = [df_master.columns.values.tolist()] + df_master.astype(str).values.tolist()
                        
                        # 5. Push the data using the most robust method (defaults to A1 automatically)
                        worksheet.update(data_to_upload)
                        
                        st.success("✅ Successfully updated your Google Sheet!")
                        
                    except gspread.exceptions.SpreadsheetNotFound:
                        st.error("🚨 Error: Could not find a Google Sheet named exactly 'Warehouse Live Sync'. Please check the spelling/capitalization!")
                    except Exception as e:
                        # We removed the hack. Now we will see the EXACT error if it fails!
                        st.error(f"🚨 Sync Failed! Exact Error: {repr(e)}")
    else:
        st.info("No data across any users yet.")
