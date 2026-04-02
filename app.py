import streamlit as st
import pandas as pd
from datetime import datetime
import json
import os
import glob
import gspread
import io

# --- Page Setup ---
st.set_page_config(page_title="Warehouse Inventory", page_icon="📦", layout="centered")

# --- USER ACCOUNTS ---
# Securely load the indestructible Master accounts from Streamlit's hidden vault
if 'USERS' not in st.session_state:
    try:
        base_users = dict(st.secrets["passwords"])
        st.session_state.USERS = base_users.copy()
    except Exception:
        st.error("🚨 Security Alert: The hidden password vault is missing! Please set up your secrets.")
        st.stop()
        
    # Pull dynamic worker accounts from the Cloud "Users" tab
    try:
        credentials = dict(st.secrets["gcp_service_account"])
        gc = gspread.service_account_from_dict(credentials)
        sh = gc.open("Warehouse Live Sync")
        try:
            users_sheet = sh.worksheet("Users")
            cloud_users = users_sheet.get_all_records()
            for row in cloud_users:
                u = str(row.get("Username", "")).strip()
                p = str(row.get("Password", "")).strip()
                if u and p:
                    st.session_state.USERS[u] = p
        except gspread.exceptions.WorksheetNotFound:
            users_sheet = sh.add_worksheet(title="Users", rows="100", cols="2")
            users_sheet.update([["Username", "Password"]])
    except Exception:
        pass # Fail silently if internet is down, Master Admin can still log in

# --- Authentication Logic ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'current_user' not in st.session_state:
    st.session_state.current_user = None

if not st.session_state.authenticated:
    st.title("🔒 Warehouse Login")
    st.markdown("Please log in to access your personal inventory workspace.")
    
    username_guess = st.text_input("Username")
    pwd_guess = st.text_input("Password", type="password")
    
    if st.button("Login", type="primary"):
        if username_guess in st.session_state.USERS and st.session_state.USERS[username_guess] == pwd_guess:
            st.session_state.authenticated = True
            st.session_state.current_user = username_guess
            st.rerun()
        else:
            st.error("Incorrect username or password.")
            
    st.stop()

# ==========================================
# IF AUTHENTICATED, RUN THE REST OF THE APP
# ==========================================

# --- Local Database Configuration ---
def get_data_file():
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

# Initialize the database on startup
load_local_db()

# --- Cloud Dictionary Integration (Categories & Models) ---
# Force Streamlit to forget the old memory structure if it's still holding onto it!
if 'cloud_models' in st.session_state and not isinstance(st.session_state.cloud_models, dict):
    del st.session_state.cloud_models

if 'cloud_models' not in st.session_state:
    st.session_state.cloud_models = {}
    if st.session_state.authenticated:
        try:
            credentials = dict(st.secrets["gcp_service_account"])
            gc = gspread.service_account_from_dict(credentials)
            sh = gc.open("Warehouse Live Sync")
            try:
                dict_sheet = sh.worksheet("Dictionary")
                records = dict_sheet.get_all_records()
                
                # Removed the aggressive intercept! All categories are allowed now.
                latest_mapping = {}
                for row in records:
                    c = str(row.get("Category", "")).strip()
                    m = str(row.get("Model", "")).strip()
                    if c and m:
                        latest_mapping[m] = c 
                        
                for m, c in latest_mapping.items():
                    if c not in st.session_state.cloud_models:
                        st.session_state.cloud_models[c] = set()
                    st.session_state.cloud_models[c].add(m)
            except gspread.exceptions.WorksheetNotFound:
                pass 
        except Exception:
            pass 

# Force "Apk" to exist as the master default
if "Apk" not in st.session_state.cloud_models:
    st.session_state.cloud_models["Apk"] = set()

# Sweep legacy local data to ensure it gets assigned to Apk
for file in glob.glob("inventory_data_*.json"):
    try:
        with open(file, "r") as f:
            user_data = json.load(f)
            for k in user_data.keys():
                m = k.split("|")[0]
                found = False
                for cat, models in st.session_state.cloud_models.items():
                    if m in models:
                        found = True
                        break
                if not found:
                    st.session_state.cloud_models["Apk"].add(m)
    except:
        pass

for k in st.session_state.data.keys():
    m = k.split("|")[0]
    found = False
    for cat, models in st.session_state.cloud_models.items():
        if m in models:
            found = True
            break
    if not found:
        st.session_state.cloud_models["Apk"].add(m)

# --- Header ---
colA, colB = st.columns([4, 1])
with colA:
    st.title(f"📦 Workspace: {st.session_state.current_user}")
with colB:
    if st.button("Logout", key="logout_btn"):
        st.session_state.authenticated = False
        st.session_state.current_user = None
        if 'data' in st.session_state: del st.session_state.data
        if 'history' in st.session_state: del st.session_state.history
        st.rerun()

st.markdown("---")

# --- Input Area (2-Step Categorized UI) ---
st.write("**Add / Remove / Move Inventory**")

categories = sorted(list(st.session_state.cloud_models.keys()))

cat_col, mod_col = st.columns(2)
with cat_col:
    cat_options = categories.copy()
    if st.session_state.current_user == "Admin":
        cat_options.append("➕ Add New Category")
        
    selected_cat = st.selectbox("Category", cat_options)
    if selected_cat == "➕ Add New Category":
        actual_cat = st.text_input("New Category Name").strip()
    else:
        actual_cat = selected_cat

with mod_col:
    if actual_cat and actual_cat in st.session_state.cloud_models:
        cat_models = sorted(list(st.session_state.cloud_models[actual_cat]))
    else:
        cat_models = []
        
    selected_mod = st.selectbox("Model Selection", ["-- Select Existing Model --", "➕ ADD NEW MODEL"] + cat_models)
    if selected_mod == "➕ ADD NEW MODEL" or selected_mod == "-- Select Existing Model --":
        actual_mod = st.text_input("Type New Model Number").upper().strip()
    else:
        actual_mod = selected_mod

# Lock in the final model
model = actual_mod

# The UI for quantities, locations, and transfers
qty_col, loc_col, dest_col = st.columns(3)
with qty_col:
    qty = st.number_input("Quantity", min_value=1, step=1, value=1)
with loc_col:
    loc = st.selectbox("Location (Add/Sub/From)", ["Warehouse", "Assembly", "Suspect"])
with dest_col:
    to_loc = st.selectbox("Destination (Moves Only)", ["Assembly", "Warehouse", "Suspect"])

# --- Math & Logic Functions ---
def modify_inventory(direction):
    if not model:
        st.error("Please select or enter a Model Number.")
        return
    if not actual_cat:
        st.error("Please select or enter a Category.")
        return
        
    key = f"{model}|{loc}"
    if key not in st.session_state.data:
        st.session_state.data[key] = 0
        
    # MOVE LOGIC
    if direction == "move":
        if loc == to_loc:
            st.warning("Source and destination cannot be the same!")
            return
            
        key_to = f"{model}|{to_loc}"
        if key_to not in st.session_state.data:
            st.session_state.data[key_to] = 0
            
        st.session_state.data[key] -= qty
        st.session_state.data[key_to] += qty
        action_word = "Moved"
    else:
        change = qty if direction == "add" else -qty
        st.session_state.data[key] += change
        action_word = "Added" if direction == "add" else "Removed"
    
    st.session_state.history.append({
        "action": action_word,
        "model": model,
        "qty": qty,
        "loc": loc,
        "to_loc": to_loc if direction == "move" else None,
        "key": key,
        "key_to": key_to if direction == "move" else None,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })
    
    save_local_db()
    
    # --- AUTO-CLOUD PUSH ---
    try:
        credentials = dict(st.secrets["gcp_service_account"])
        gc = gspread.service_account_from_dict(credentials)
        sh = gc.open("Warehouse Live Sync")
        
        # Dictionary Update
        is_new = True
        if actual_cat in st.session_state.cloud_models:
            if model in st.session_state.cloud_models[actual_cat]:
                is_new = False
                
        if is_new:
            if actual_cat not in st.session_state.cloud_models:
                st.session_state.cloud_models[actual_cat] = set()
            st.session_state.cloud_models[actual_cat].add(model)
            
            try:
                dict_sheet = sh.worksheet("Dictionary")
                if len(dict_sheet.row_values(1)) < 2:
                    dict_sheet.insert_row(["Category", "Model"], index=1)
            except gspread.exceptions.WorksheetNotFound:
                dict_sheet = sh.add_worksheet(title="Dictionary", rows="1000", cols="2")
                dict_sheet.update([["Category", "Model"]])
            
            dict_sheet.append_row([actual_cat, model])
            st.toast(f"☁️ '{model}' instantly saved to category '{actual_cat}'!")
            
        # Audit Log Update
        try:
            audit_sheet = sh.worksheet("Audit Log")
        except gspread.exceptions.WorksheetNotFound:
            audit_sheet = sh.add_worksheet(title="Audit Log", rows="1000", cols="1")
            audit_sheet.update([["Audit Trail"]])
            
        full_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        if direction == "move":
            log_entry = f"[{full_timestamp}] {st.session_state.current_user} MOVED {qty} of Model {model} (From: {loc} ➔ To: {to_loc})"
        else:
            log_entry = f"[{full_timestamp}] {st.session_state.current_user} {action_word.upper()} {qty} of Model {model} (Location: {loc})"
        
        audit_sheet.append_row([log_entry])
    except Exception:
        pass
    
    if direction == "add":
        st.success(f"✓ {action_word} {qty} {model} ({loc}) [Total: {st.session_state.data[key]}]")
    elif direction == "sub":
        st.warning(f"⚠ {action_word} {qty} {model} ({loc}) [Total: {st.session_state.data[key]}]")
    else:
        st.info(f"⇆ {action_word} {qty} {model} ({loc} ➔ {to_loc})")

# --- Action Buttons ---
btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
with btn_col1:
    if st.button("ADD (+)", use_container_width=True, type="primary"):
        modify_inventory("add")
        st.rerun() 
with btn_col2:
    if st.button("SUB (-)", use_container_width=True):
        modify_inventory("sub")
        st.rerun()
with btn_col3:
    if st.button("MOVE (⇆)", use_container_width=True):
        modify_inventory("move")
        st.rerun()
with btn_col4:
    if st.button("↺ Undo", use_container_width=True):
        if not st.session_state.history:
            st.warning("Nothing to undo!")
        else:
            last = st.session_state.history.pop()
            if last.get("action") == "Moved":
                st.session_state.data[last["key"]] += last["qty"]
                st.session_state.data[last["key_to"]] -= last["qty"]
            else:
                change = last["qty"] if last["action"] == "Added" else -last["qty"]
                st.session_state.data[last["key"]] -= change
                
            save_local_db()
            st.info(f"↺ Undid last action for {last['model']}")
            st.rerun()

st.markdown("---")

# --- Live Report Area ---
st.subheader("📊 Live List (In Stock Only)")

report_rows = []

# Gather unique models from both cloud categories and local data
unique_models = set()
model_to_cat = {}
for cat, models in st.session_state.cloud_models.items():
    unique_models.update(models)
    for m in models:
        model_to_cat[m] = cat

for k in st.session_state.data.keys():
    unique_models.add(k.split("|")[0])

for m in sorted(list(unique_models)):
    wh = st.session_state.data.get(f"{m}|Warehouse", 0)
    asm = st.session_state.data.get(f"{m}|Assembly", 0)
    susp = st.session_state.data.get(f"{m}|Suspect", 0)
    total = wh + asm
    
    if total != 0 or susp != 0:
        report_rows.append({
            "_HiddenCat": model_to_cat.get(m, "Apk"), # Changed to a hidden background variable
            "Model": m, 
            "Warehouse": wh, 
            "Assembly": asm, 
            "Total": total, 
            "Suspect (Bad)": susp
        })

if report_rows:
    df = pd.DataFrame(report_rows)
    df = df.sort_values(by=["_HiddenCat", "Model"])
    
    # Hide the category from the actual screen
    display_df = df.drop(columns=["_HiddenCat"])
    
    search = st.text_input("🔍 Search Models to Filter:")
    if search:
        display_df = display_df[display_df["Model"].str.contains(search.upper())]
        
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    
    # --- TABBED EXCEL DOWNLOAD FOR WORKERS ---
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for cat in sorted(df['_HiddenCat'].unique()):
                cat_df = df[df['_HiddenCat'] == cat].drop(columns=['_HiddenCat'])
                cat_df.to_excel(writer, sheet_name=str(cat)[:31], index=False)
        file_data = output.getvalue()
        file_name = f"Inventory_{st.session_state.current_user}_{now}.xlsx"
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        btn_label = "📥 DOWNLOAD EXCEL (SEPARATE TABS)"
    except ModuleNotFoundError:
        csv_text = ""
        for cat in sorted(df['_HiddenCat'].unique()):
            cat_df = df[df['_HiddenCat'] == cat].drop(columns=['_HiddenCat'])
            csv_text += f"--- {cat.upper()} ---\n"
            csv_text += cat_df.to_csv(index=False)
            csv_text += "\n"
        file_data = csv_text.encode('utf-8')
        file_name = f"Inventory_{st.session_state.current_user}_{now}.csv"
        mime_type = "text/csv"
        btn_label = "📥 DOWNLOAD CSV (SEPARATED)"

    st.download_button(
        label=btn_label,
        data=file_data,
        file_name=file_name,
        mime=mime_type,
    )
else:
    st.info("No items currently in stock. Add items above.")

with st.expander("Show Recent History Log"):
    if st.session_state.history:
        for item in reversed(st.session_state.history[-10:]):
            if item.get("action") == "Moved":
                st.text(f"[{item['timestamp']}] {item['action']} {item['qty']} x {item['model']} ({item['loc']} ➔ {item.get('to_loc')})")
            else:
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
            st.warning("Are you sure? This sets ALL USERS' counts to 0.")
            if st.button("Yes, Reset All Counts", use_container_width=True):
                for key in st.session_state.data:
                    st.session_state.data[key] = 0
                st.session_state.history = []
                save_local_db()
                
                for file in glob.glob("inventory_data_*.json"):
                    try:
                        with open(file, "r") as f:
                            other_data = json.load(f)
                        for k in other_data:
                            other_data[k] = 0
                        with open(file, "w") as f:
                            json.dump(other_data, f)
                    except:
                        pass
                for file in glob.glob("inventory_history_*.json"):
                    try:
                        with open(file, "w") as f:
                            json.dump([], f)
                    except:
                        pass
                st.rerun()
        else:
            st.warning("Are you sure? This sets all your personal counts to 0.")
            if st.button("Yes, Reset My Counts", use_container_width=True):
                for key in st.session_state.data:
                    st.session_state.data[key] = 0
                st.session_state.history = []  
                save_local_db()
                st.rerun()

with reset_col2:
    if st.session_state.current_user == "Admin":
        with st.expander("🗑️ Wipe Everything"):
            st.warning("🚨 DANGER: This permanently erases all your models and counts locally.")
            st.write("To unlock the delete button, type **WIPE EVERYTHING** below:")
            confirm_wipe = st.text_input("Confirmation text", label_visibility="collapsed")
            
            # The button stays greyed out and unclickable until the text matches exactly
            if st.button("Yes, Wipe My Data", use_container_width=True, type="primary", disabled=(confirm_wipe != "WIPE EVERYTHING")):
                st.session_state.data = {}
                st.session_state.history = {}
                
                for file in glob.glob("inventory_data_*.json"):
                    try: os.remove(file)
                    except: pass
                for file in glob.glob("inventory_history_*.json"):
                    try: os.remove(file)
                    except: pass
                
                save_local_db() 
                st.rerun()

st.markdown("---")

if st.session_state.current_user == "Admin":
    # --- NEW TOOL: RE-ASSIGN CATEGORIES ---
    with st.expander("🔀 Move Model to Another Category"):
        st.write("Instantly reorganize your catalog. Select a destination category, then pick the model you want to move into it.")
        move_col1, move_col2, move_col3 = st.columns([2, 2, 1])
        
        with move_col1:
            target_cat = st.selectbox("1. Destination Category:", ["-- Select --"] + categories, key="move_cat")
            
        with move_col2:
            all_known_models = sorted(list(unique_models))
            if target_cat != "-- Select --":
                # Filter out models that are ALREADY inside the target category
                models_in_target = st.session_state.cloud_models.get(target_cat, set())
                available_models = [m for m in all_known_models if m not in models_in_target]
            else:
                available_models = all_known_models
                
            model_to_move = st.selectbox("2. Select Model to Move:", ["-- Select --"] + available_models, key="move_mod")
            
        with move_col3:
            st.markdown("<br>", unsafe_allow_html=True) # Aligns the button with the dropdowns
            if st.button("Move", use_container_width=True, type="primary"):
                if model_to_move != "-- Select --" and target_cat != "-- Select --":
                    # 1. Remove from all old categories
                    for c in list(st.session_state.cloud_models.keys()):
                        if model_to_move in st.session_state.cloud_models[c]:
                            st.session_state.cloud_models[c].remove(model_to_move)
                    
                    # 2. Add to the new category
                    if target_cat not in st.session_state.cloud_models:
                        st.session_state.cloud_models[target_cat] = set()
                    st.session_state.cloud_models[target_cat].add(model_to_move)
                    
                    # 3. Force a cloud sync so it remembers forever
                    try:
                        credentials = dict(st.secrets["gcp_service_account"])
                        gc = gspread.service_account_from_dict(credentials)
                        sh = gc.open("Warehouse Live Sync")
                        dict_sheet = sh.worksheet("Dictionary")
                        dict_sheet.clear()
                        dict_upload = [["Category", "Model"]]
                        for c, models_in_cat in st.session_state.cloud_models.items():
                            for m_val in models_in_cat:
                                dict_upload.append([c, m_val])
                        dict_sheet.update(dict_upload)
                        st.success(f"✅ Model '{model_to_move}' successfully moved to '{target_cat}'!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to sync category move to cloud: {e}")
                else:
                    st.warning("Please select both a model and a destination category.")

    with st.expander("❌ Delete a Specific Model (Fix Typos)"):
        st.write("Select a model to permanently remove from memory:")
        del_col1, del_col2 = st.columns([3, 1])
        with del_col1:
            all_known_models = sorted(list(unique_models))
            model_to_delete = st.selectbox("Select model:", ["-- Select --"] + all_known_models, label_visibility="collapsed")
        with del_col2:
            if st.button("Delete Model", use_container_width=True, type="primary"):
                if model_to_delete and model_to_delete != "-- Select --":
                    keys_to_delete = [k for k in st.session_state.data.keys() if k.startswith(f"{model_to_delete}|")]
                    for k in keys_to_delete:
                        del st.session_state.data[k]
                    save_local_db()
                    
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

    with st.expander("❌ Delete a Category"):
        st.write("Remove a category. Any models inside it will be safely moved to the default 'Apk' category so no inventory is lost.")
        cat_to_del = st.selectbox("Select Category to Delete", ["-- Select --"] + [c for c in categories if c != "Apk"])
        if st.button("Delete Category", use_container_width=True, type="primary"):
            if cat_to_del != "-- Select --":
                if cat_to_del in st.session_state.cloud_models:
                    st.session_state.cloud_models["Apk"].update(st.session_state.cloud_models[cat_to_del])
                    del st.session_state.cloud_models[cat_to_del]
                    
                    try:
                        credentials = dict(st.secrets["gcp_service_account"])
                        gc = gspread.service_account_from_dict(credentials)
                        sh = gc.open("Warehouse Live Sync")
                        dict_sheet = sh.worksheet("Dictionary")
                        dict_sheet.clear()
                        dict_upload = [["Category", "Model"]]
                        for c, models_in_cat in st.session_state.cloud_models.items():
                            for m_val in models_in_cat:
                                dict_upload.append([c, m_val])
                        dict_sheet.update(dict_upload)
                        st.success(f"✅ Category '{cat_to_del}' deleted. Its models were safely moved to 'Apk'.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to sync deletion to cloud: {e}")

    with st.expander("☁️ Clear Cloud Audit Log"):
        st.warning("This will permanently erase the historical Audit Log in your Google Sheet.")
        if st.button("Erase Cloud Audit Log", use_container_width=True, type="primary"):
            try:
                with st.spinner("Connecting to Google to wipe the log..."):
                    credentials = dict(st.secrets["gcp_service_account"])
                    gc = gspread.service_account_from_dict(credentials)
                    sh = gc.open("Warehouse Live Sync")
                    try:
                        audit_sheet = sh.worksheet("Audit Log")
                        audit_sheet.clear()
                        audit_sheet.update([["Audit Trail"]]) 
                        st.success("✅ The Cloud Audit Log has been completely wiped clean!")
                    except gspread.exceptions.WorksheetNotFound:
                        st.info("No Audit Log exists in the cloud yet, nothing to wipe.")
            except Exception as e:
                st.error(f"Failed to clear log: {e}")

    with st.expander("👥 Manage Worker Accounts"):
        st.write("Add or remove worker accounts. (Admin locked in secrets).")
        acc_col1, acc_col2 = st.columns(2)
        
        with acc_col1:
            st.markdown("**Add New User**")
            new_user = st.text_input("New Username").strip()
            new_pwd = st.text_input("New Password").strip()
            if st.button("Add User", type="primary", use_container_width=True):
                if new_user and new_pwd:
                    if new_user in st.session_state.USERS:
                        st.warning(f"User '{new_user}' already exists!")
                    else:
                        try:
                            credentials = dict(st.secrets["gcp_service_account"])
                            gc = gspread.service_account_from_dict(credentials)
                            sh = gc.open("Warehouse Live Sync")
                            users_sheet = sh.worksheet("Users")
                            users_sheet.append_row([new_user, new_pwd])
                            st.session_state.USERS[new_user] = new_pwd
                            st.success(f"✅ User '{new_user}' added successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to add user to cloud: {e}")
                else:
                    st.warning("Please enter both username and password.")
                    
        with acc_col2:
            st.markdown("**Delete User**")
            base_users = list(st.secrets["passwords"].keys())
            deletable_users = [u for u in st.session_state.USERS.keys() if u not in base_users]
            
            if deletable_users:
                user_to_delete = st.selectbox("Select Worker to Remove", ["-- Select --"] + deletable_users, label_visibility="collapsed")
                if st.button("Delete User", use_container_width=True):
                    if user_to_delete != "-- Select --":
                        try:
                            credentials = dict(st.secrets["gcp_service_account"])
                            gc = gspread.service_account_from_dict(credentials)
                            sh = gc.open("Warehouse Live Sync")
                            users_sheet = sh.worksheet("Users")
                            
                            del st.session_state.USERS[user_to_delete]
                            
                            cloud_upload = [["Username", "Password"]]
                            for u, p in st.session_state.USERS.items():
                                if u not in base_users:
                                    cloud_upload.append([u, p])
                                    
                            users_sheet.clear()
                            users_sheet.update(cloud_upload)
                            st.success(f"✅ User '{user_to_delete}' has been removed.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete user: {e}")
            else:
                st.info("No cloud worker accounts to delete.")

# --- ADMIN MASTER VIEW ---
if st.session_state.current_user == "Admin":
    st.markdown("---")
    st.header("👑 Admin Master Dashboard")
    st.write("Aggregated totals combined from all users' personal workspaces.")
    
    master_data = {}
    for file in glob.glob("inventory_data_*.json"):
        with open(file, "r") as f:
            try:
                user_data = json.load(f)
                for k, v in user_data.items():
                    master_data[k] = master_data.get(k, 0) + v
            except:
                pass
                
    master_rows = []
    master_models = sorted(list(set([k.split("|")[0] for k in master_data.keys()])))
    
    master_model_to_cat = {}
    for cat, models in st.session_state.cloud_models.items():
        for m in models:
            master_model_to_cat[m] = cat
    
    for m in master_models:
        wh = master_data.get(f"{m}|Warehouse", 0)
        asm = master_data.get(f"{m}|Assembly", 0)
        susp = master_data.get(f"{m}|Suspect", 0)
        total = wh + asm
        
        if total != 0 or susp != 0:
            master_rows.append({
                "_HiddenCat": master_model_to_cat.get(m, "Apk"), # Changed to hidden
                "Model": m, 
                "Warehouse": wh, 
                "Assembly": asm, 
                "Total": total, 
                "Suspect (Bad)": susp
            })
            
    if master_rows:
        df_master = pd.DataFrame(master_rows)
        df_master = df_master.sort_values(by=["_HiddenCat", "Model"])
        
        # --- 🦅 THE EAGLE EYE (VISUAL ANALYTICS) ---
        st.markdown("### 🦅 Eagle Eye Dashboard")
        
        met1, met2, met3 = st.columns(3)
        met1.metric("📦 Total Items in Stock", f"{int(df_master['Total'].sum()):,}")
        met2.metric("🏷️ Active Categories", df_master["_HiddenCat"].nunique())
        met3.metric("🚨 Suspect (Bad) Parts", f"{int(df_master['Suspect (Bad)'].sum()):,}", delta_color="inverse")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # We removed the Category chart and let the Top 10 Models chart take the full width!
        st.markdown("**Warehouse vs Assembly (Top 10 Models)**")
        top_models = df_master.sort_values("Total", ascending=False).head(10)
        if not top_models.empty:
            chart_data = top_models.set_index("Model")[["Warehouse", "Assembly"]]
            st.bar_chart(chart_data, color=["#1f77b4", "#ff7f0e"])

        st.markdown("---")
        st.markdown("### 📋 Master Data Table")
        
        display_df_master = df_master.drop(columns=["_HiddenCat"])
        st.dataframe(display_df_master, use_container_width=True, hide_index=True)
        
        now = datetime.now().strftime("%Y-%m-%d_%H-%M")
        
        # --- NEW: MASTER TABBED EXCEL DOWNLOAD ---
        try:
            output_master = io.BytesIO()
            with pd.ExcelWriter(output_master, engine='openpyxl') as writer:
                for cat in sorted(df_master['_HiddenCat'].unique()):
                    cat_df = df_master[df_master['_HiddenCat'] == cat].drop(columns=['_HiddenCat'])
                    cat_df.to_excel(writer, sheet_name=str(cat)[:31], index=False)
            file_data_master = output_master.getvalue()
            file_name_master = f"Inventory_MASTER_{now}.xlsx"
            mime_type_master = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            btn_label_master = "📥 DOWNLOAD MASTER EXCEL (TABS)"
        except ModuleNotFoundError:
            csv_text_master = ""
            for cat in sorted(df_master['_HiddenCat'].unique()):
                cat_df = df_master[df_master['_HiddenCat'] == cat].drop(columns=['_HiddenCat'])
                csv_text_master += f"--- {cat.upper()} ---\n"
                csv_text_master += cat_df.to_csv(index=False)
                csv_text_master += "\n"
            file_data_master = csv_text_master.encode('utf-8')
            file_name_master = f"Inventory_MASTER_{now}.csv"
            mime_type_master = "text/csv"
            btn_label_master = "📥 DOWNLOAD MASTER CSV (SEPARATED)"
        
        col_dl, col_cloud = st.columns(2)
        
        with col_dl:
            st.download_button(
                label=btn_label_master,
                data=file_data_master,
                file_name=file_name_master,
                mime=mime_type_master,
                type="primary" 
            )
            
        with col_cloud:
            if st.button("☁️ Sync to Google Sheets", use_container_width=True):
                with st.spinner("Syncing to the Cloud..."):
                    try:
                        credentials = dict(st.secrets["gcp_service_account"])
                        gc = gspread.service_account_from_dict(credentials)
                        sh = gc.open("Warehouse Live Sync")
                        
                        today_str = datetime.now().strftime("%Y-%m-%d")
                        snapshot_title = f"Snapshot: {today_str}"
                        
                        try:
                            worksheet = sh.worksheet(snapshot_title)
                        except gspread.exceptions.WorksheetNotFound:
                            worksheet = sh.add_worksheet(title=snapshot_title, rows="1000", cols="5")
                        
                        worksheet.clear()
                        # Make sure we don't upload the hidden category to the daily snapshot!
                        data_to_upload = [display_df_master.columns.values.tolist()] + display_df_master.astype(str).values.tolist()
                        worksheet.update(data_to_upload)
                        
                        all_sheets = sh.worksheets()
                        snapshot_sheets = [ws for ws in all_sheets if ws.title.startswith("Snapshot: ")]
                        snapshot_sheets.sort(key=lambda ws: ws.title)
                        
                        while len(snapshot_sheets) > 2:
                            ws_to_delete = snapshot_sheets.pop(0)
                            sh.del_worksheet(ws_to_delete)
                        
                        try:
                            dict_sheet = sh.worksheet("Dictionary")
                        except gspread.exceptions.WorksheetNotFound:
                            dict_sheet = sh.add_worksheet(title="Dictionary", rows="1000", cols="2")

                        dict_sheet.clear()
                        dict_upload = [["Category", "Model"]]
                        for cat, models_in_cat in st.session_state.cloud_models.items():
                            for m_val in models_in_cat:
                                dict_upload.append([cat, m_val])
                                
                        dict_sheet.update(dict_upload)
                        
                        st.success(f"✅ Successfully updated '{snapshot_title}' and Cloud Dictionary!")
                        
                    except gspread.exceptions.SpreadsheetNotFound:
                        st.error("🚨 Error: Could not find 'Warehouse Live Sync' Google Sheet.")
                    except Exception as e:
                        st.error(f"🚨 Sync Failed! Exact Error: {repr(e)}")
    else:
        st.info("No data across any users yet.")
