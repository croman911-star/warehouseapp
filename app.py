import streamlit as st
import json
import os
import glob
from datetime import datetime
import pandas as pd
import gspread
import io
import re

st.set_page_config(page_title="Warehouse System", layout="wide")

# --- API Caching (Stop Hammering Google) ---
if 'gc' not in st.session_state or 'sh' not in st.session_state:
    try:
        credentials = dict(st.secrets["gcp_service_account"])
        st.session_state.gc = gspread.service_account_from_dict(credentials)
        st.session_state.sh = st.session_state.gc.open("Warehouse Live Sync")
    except Exception:
        st.session_state.gc = None
        st.session_state.sh = None

# --- Auth State ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None

# --- User Authentication DB ---
USER_FILE = "warehouse_users.json"
if not os.path.exists(USER_FILE):
    default_users = {"Admin": "1234", "Worker1": "1234", "Worker2": "1234"}
    with open(USER_FILE, "w") as f:
        json.dump(default_users, f)

with open(USER_FILE, "r") as f:
    auth_db = json.load(f)

# --- Helper: File Paths & Atomic DB Ops ---
def get_data_file():
    return f"inventory_data_{st.session_state.current_user}.json"

def get_hist_file():
    return f"inventory_history_{st.session_state.current_user}.json"

def load_local_db():
    if not st.session_state.authenticated:
        return

    st.session_state.data = {}
    st.session_state.history = []

    data_file = get_data_file()
    hist_file = get_hist_file()

    if os.path.exists(data_file):
        try:
            with open(data_file, "r") as f:
                st.session_state.data = json.load(f)
        except Exception: pass

    if os.path.exists(hist_file):
        try:
            with open(hist_file, "r") as f:
                st.session_state.history = json.load(f)
        except Exception: pass

def save_local_db():
    data_file = get_data_file()
    hist_file = get_hist_file()

    # ATOMIC WRITE: Write to .tmp first, then swap to prevent file corruption
    for path, obj in [(data_file, st.session_state.data), (hist_file, st.session_state.history)]:
        tmp = path + ".tmp"
        try:
            with open(tmp, 'w') as f:
                json.dump(obj, f)
            os.replace(tmp, path)
        except Exception: pass

def push_dictionary_entry(cat, model):
    if not st.session_state.sh:
        return
    try:
        try:
            dict_sheet = st.session_state.sh.worksheet("Dictionary")
        except gspread.exceptions.WorksheetNotFound:
            dict_sheet = st.session_state.sh.add_worksheet(title="Dictionary", rows="1000", cols="2")
            dict_sheet.update(values=[["Category", "Model"]], range_name="A1")
        dict_sheet.append_row([cat, model])
    except Exception:
        st.toast("⚠️ Cloud dictionary sync delayed. Saved locally.", icon="⏳")

# --- Login Screen ---
if not st.session_state.authenticated:
    st.title("Warehouse Login")
    users = sorted(list(auth_db.keys()))
    sel_user = st.selectbox("Select User", users)
    pwd = st.text_input("Password", type="password")

    if st.button("Login"):
        if pwd == auth_db.get(sel_user):
            st.session_state.authenticated = True
            st.session_state.current_user = sel_user
            load_local_db()
            st.rerun()
        else:
            st.error("Incorrect password. Default is 1234.")
    st.stop()

# --- Initialize Session DB ---
if 'data' not in st.session_state:
    load_local_db()

# --- Cloud Dictionary Integration ---
if 'cloud_models' in st.session_state and not isinstance(st.session_state.cloud_models, dict):
    del st.session_state.cloud_models

if 'cloud_models' not in st.session_state:
    st.session_state.cloud_models = {}
    if st.session_state.sh:
        try:
            dict_sheet = st.session_state.sh.worksheet("Dictionary")
            records = dict_sheet.get_all_records()
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
        except Exception: pass

if "Apk" not in st.session_state.cloud_models:
    st.session_state.cloud_models["Apk"] = set()

for file in glob.glob("inventory_data_*.json"):
    try:
        with open(file, "r") as f:
            user_data = json.load(f)
            for k in user_data.keys():
                m = k.split("|")[0]
                found = any(m in models for models in st.session_state.cloud_models.values())
                if not found: st.session_state.cloud_models["Apk"].add(m)
    except: pass

for k in st.session_state.data.keys():
    m = k.split("|")[0]
    found = any(m in models for models in st.session_state.cloud_models.values())
    if not found: st.session_state.cloud_models["Apk"].add(m)

# --- Clean Up Empty Categories ---
keys_to_del = [c for c, mods in st.session_state.cloud_models.items() if not mods and c != "Apk"]
for c in keys_to_del:
    del st.session_state.cloud_models[c]

# --- UI Header ---
colA, colB = st.columns([4, 1])
colA.title(f"Warehouse Tracker - {st.session_state.current_user}")
if colB.button("Logout"):
    st.session_state.authenticated = False
    st.session_state.current_user = None
    st.rerun()

# --- Live Calculation Engine ---
master_data = {}
for file in glob.glob("inventory_data_*.json"):
    try:
        with open(file, "r") as f:
            other_data = json.load(f)
        for k, v in other_data.items():
            master_data[k] = master_data.get(k, 0) + v
    except: pass

unique_models = set([k.split("|")[0] for k in master_data.keys()])
for models_in_cat in st.session_state.cloud_models.values():
    unique_models.update(models_in_cat)

LOCATIONS = ["Warehouse", "Assembly", "Suspect"]

def modify_inventory(action_type):
    load_local_db()

    cat = st.session_state.get("cat_sel")
    model = st.session_state.get("mod_sel")
    qty = st.session_state.get("qty_input")
    loc = st.session_state.get("loc_sel", "Warehouse")
    loc_to = st.session_state.get("loc_to_sel", "Assembly")

    if not model or model == "-- Select --" or qty <= 0 or not cat or cat == "➕ Add New Category":
        return

    key = f"{model}|{loc}"
    full_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    log_msg = ""

    is_new_model = cat not in st.session_state.cloud_models or model not in st.session_state.cloud_models[cat]

    # --- NEW: Calculate Global Total instantly before math ---
    global_count = 0
    for file in glob.glob("inventory_data_*.json"):
        try:
            with open(file, "r") as f:
                od = json.load(f)
                global_count += od.get(key, 0)
        except: pass

    if action_type == "add":
        st.session_state.data[key] = st.session_state.data.get(key, 0) + qty
        st.session_state.history.append({"action": "Added", "model": model, "qty": qty, "loc": loc, "key": key})
        log_msg = f"[{full_timestamp}] {st.session_state.current_user} Added {qty} x {model} ({loc})"

        if cat not in st.session_state.cloud_models:
            st.session_state.cloud_models[cat] = set()
        st.session_state.cloud_models[cat].add(model)

        if is_new_model:
            push_dictionary_entry(cat, model)

    elif action_type == "sub":
        # Caps the subtraction at the Global Total so you can't go below 0 globally
        allowed_qty = min(qty, global_count)
        if allowed_qty <= 0:
            st.warning("Cannot subtract. Global inventory is already 0.")
            return
            
        st.session_state.data[key] = st.session_state.data.get(key, 0) - allowed_qty
        st.session_state.history.append({"action": "Removed", "model": model, "qty": allowed_qty, "loc": loc, "key": key})
        log_msg = f"[{full_timestamp}] {st.session_state.current_user} Removed {allowed_qty} x {model} ({loc})"

    elif action_type == "move":
        if loc == loc_to:
            st.warning("Source and destination cannot be the same!")
            return
            
        allowed_qty = min(qty, global_count)
        if allowed_qty <= 0:
            st.warning("Cannot move. Source location is empty.")
            return
            
        key_to = f"{model}|{loc_to}"
        st.session_state.data[key] = st.session_state.data.get(key, 0) - allowed_qty
        st.session_state.data[key_to] = st.session_state.data.get(key_to, 0) + allowed_qty
        st.session_state.history.append({
            "action": "Moved", "model": model, "qty": allowed_qty, "loc": loc, "to_loc": loc_to, "key": key, "key_to": key_to
        })
        log_msg = f"[{full_timestamp}] {st.session_state.current_user} Moved {allowed_qty} x {model} ({loc} ➔ {loc_to})"

    save_local_db()

    if st.session_state.sh:
        try:
            audit_sheet = st.session_state.sh.worksheet("Audit Log")
            audit_sheet.append_row([log_msg])
        except Exception:
            st.toast("⚠️ Cloud sync delayed due to traffic. Saved locally.", icon="⏳")

# --- UI Panel ---
categories = sorted(list(st.session_state.cloud_models.keys()))
cat_opts = categories + (["➕ Add New Category"] if st.session_state.current_user == "Admin" else [])

cat_sel = st.selectbox("Category:", cat_opts, key="cat_sel_raw")

if cat_sel == "➕ Add New Category":
    new_cat = st.text_input("Enter new category name:")
    if new_cat:
        cat_sel = new_cat
        if cat_sel not in st.session_state.cloud_models:
            st.session_state.cloud_models[cat_sel] = set()

st.session_state.cat_sel = cat_sel

mods_for_cat = sorted(list(st.session_state.cloud_models.get(cat_sel, [])))
mod_opts = ["-- Select --"] + mods_for_cat + ["➕ ADD NEW MODEL"]

mod_sel = st.selectbox("Model Selection:", mod_opts, key="mod_sel_raw")
if mod_sel == "➕ ADD NEW MODEL":
    mod_sel = st.text_input("Enter New Model Number:").strip().replace("|", "-")
st.session_state.mod_sel = mod_sel

qty_col, loc_col, loc_to_col = st.columns(3)
with qty_col:
    st.number_input("Quantity:", min_value=1, value=1, step=1, key="qty_input")
with loc_col:
    st.selectbox("Location (Add/Sub/From):", LOCATIONS, key="loc_sel")
with loc_to_col:
    st.selectbox("Destination (Move only):", LOCATIONS, index=1, key="loc_to_sel")

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
            # 1. Read the absolute latest files from the disk
            load_local_db()

            # --- NEW SAFETY CATCH ---
            # 2. Check AGAIN to make sure a Reset didn't just wipe the history file!
            if not st.session_state.history:
                st.warning("The board is fresh! Nothing to undo.")
            else:
                last = st.session_state.history.pop()
                
                # We do not use max(0) here so the global balance remains flawless
                if last.get("action") == "Moved":
                    st.session_state.data[last["key"]] = st.session_state.data.get(last["key"], 0) + last["qty"]
                    st.session_state.data[last["key_to"]] = st.session_state.data.get(last["key_to"], 0) - last["qty"]
                else:
                    change = last["qty"] if last["action"] == "Added" else -last["qty"]
                    st.session_state.data[last["key"]] = st.session_state.data.get(last["key"], 0) - change

                save_local_db()

                if st.session_state.sh:
                    try:
                        audit_sheet = st.session_state.sh.worksheet("Audit Log")
                        full_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
                        if last.get("action") == "Moved":
                            undo_msg = f"[{full_timestamp}] ↺ UNDO: {st.session_state.current_user} reversed move of {last['qty']} x {last['model']} ({last['loc']} ➔ {last.get('to_loc')})"
                        else:
                            undo_msg = f"[{full_timestamp}] ↺ UNDO: {st.session_state.current_user} reversed {last['action'].lower()} of {last['qty']} x {last['model']} ({last['loc']})"
                        audit_sheet.append_row([undo_msg])
                    except Exception:
                        st.toast("⚠️ Cloud sync delayed. Saved locally.", icon="⏳")

                st.info(f"↺ Undid last action for {last['model']}")
                st.rerun()

st.markdown("<br>", unsafe_allow_html=True)
with st.expander("🧹 Reset My Daily Count"):
    st.write("Start a fresh slate for the day. This zeroes out **only your** personal counts.")
    confirm_my_reset = st.checkbox("I am ready to clear my board.", key="chk_my_reset")
    if st.button("Reset My Count", type="primary", disabled=not confirm_my_reset):
        # 1. Clear active memory
        st.session_state.data = {}
        st.session_state.history = []
        
        # --- NEW: Hard-delete this specific worker's files to bypass Windows locks! ---
        try: os.remove(get_data_file())
        except: pass
        try: os.remove(get_hist_file())
        except: pass
        
        # 2. Create fresh empty files
        save_local_db()
        
        # 3. Log it in the cloud
        if st.session_state.sh:
            try:
                audit_sheet = st.session_state.sh.worksheet("Audit Log")
                full_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
                audit_sheet.append_row([f"[{full_timestamp}] 🧹 WORKER RESET: {st.session_state.current_user} cleared their personal counts for a fresh day."])
            except Exception:
                pass
        st.rerun()

st.markdown("---")

# --- Live Data Table ---
st.markdown("---")

# --- Live Data Table ---
data_list = []
for m in unique_models:
    w_cnt = master_data.get(f"{m}|Warehouse", 0)
    a_cnt = master_data.get(f"{m}|Assembly", 0)
    b_cnt = master_data.get(f"{m}|Suspect", 0) 

    found_cat = "Apk"
    for c, models in st.session_state.cloud_models.items():
        if m in models:
            found_cat = c
            break

    if w_cnt > 0 or a_cnt > 0 or b_cnt > 0:
        data_list.append({
            "_HiddenCat": found_cat,
            "Model": m,
            "Warehouse": w_cnt,
            "Assembly": a_cnt,
            "Suspect (Bad)": b_cnt,
            "Total": w_cnt + a_cnt
        })

df_master = pd.DataFrame(data_list)
if not df_master.empty:
    df_master = df_master.sort_values(by=["_HiddenCat", "Model"])

    if st.session_state.current_user == "Admin":
        st.markdown("### 🦅 Eagle Eye Dashboard")
        met1, met2, met3 = st.columns(3)
        met1.metric("📦 Total Items in Stock", f"{int(df_master['Total'].sum()):,}")
        met2.metric("🏷️ Active Categories", df_master["_HiddenCat"].nunique())
        met3.metric("🚨 Suspect (Bad) Parts", f"{int(df_master['Suspect (Bad)'].sum()):,}", delta_color="inverse")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("**Warehouse vs Assembly (Top 10 Models)**")
        top_models = df_master.sort_values("Total", ascending=False).head(10)
        if not top_models.empty:
            chart_data = top_models.set_index("Model")[["Warehouse", "Assembly"]]
            st.bar_chart(chart_data, color=["#1f77b4", "#ff7f0e"])

        st.markdown("---")
        st.markdown("### 📋 Master Data Table")

    display_df = df_master.drop(columns=["_HiddenCat"]) if "_HiddenCat" in df_master.columns else df_master
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Multi-Tab Excel Export
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for cat_name in df_master["_HiddenCat"].unique():
            cat_df = df_master[df_master["_HiddenCat"] == cat_name].drop(columns=["_HiddenCat"])
            
            safe_sheet_name = re.sub(r'[\\/*?:\[\]]', '', str(cat_name))[:31]
            cat_df.to_excel(writer, sheet_name=safe_sheet_name, index=False)

            worksheet = writer.sheets[safe_sheet_name]
            for col in worksheet.columns:
                max_length = max(len(str(cell.value)) for cell in col) + 2
                worksheet.column_dimensions[col[0].column_letter].width = max_length

    st.download_button("📥 Download Multi-Tab Excel (.xlsx)", data=output.getvalue(), file_name=f"Warehouse_Inventory_{datetime.now().strftime('%Y-%m-%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("Warehouse is currently empty.")

st.markdown("---")

# --- System Management (Admin Only) ---
if st.session_state.current_user == "Admin":
    st.markdown("### ⚙️ System Management")

    sync_col, null_col = st.columns([1, 2])
    with sync_col:
        if st.button("☁️ Sync to Google Sheets", type="primary", use_container_width=True):
            if st.session_state.sh:
                try:
                    snap_sheet = st.session_state.sh.worksheet("Snapshots")
                    snap_data = []
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    for _, row in df_master.iterrows():
                        snap_data.append([today_str, row["_HiddenCat"], row["Model"], row["Total"]])
                    if snap_data:
                        snap_sheet.append_rows(snap_data)

                    dict_sheet = st.session_state.sh.worksheet("Dictionary")
                    dict_sheet.clear()
                    dict_upload = [["Category", "Model"]]
                    for c, models_in_cat in st.session_state.cloud_models.items():
                        for m_val in models_in_cat:
                            dict_upload.append([c, m_val])
                    dict_sheet.update(values=dict_upload, range_name="A1")

                    st.success("✅ Synced to Cloud Successfully!")
                except Exception as e:
                    st.error(f"Cloud Error: {e}")
            else:
                st.error("Google Sheets is not connected.")

    with st.expander("☁️ Clear Cloud Audit Log"):
        st.write("Erase the running history from the Google Sheet (Starts fresh).")
        if st.button("Erase Cloud Audit Log"):
            if st.session_state.sh:
                try:
                    audit_sheet = st.session_state.sh.worksheet("Audit Log")
                    audit_sheet.clear()
                    audit_sheet.update(values=[["Action Log"]], range_name="A1")
                    st.success("Audit Log wiped from Cloud.")
                except Exception as e:
                    st.error(f"Failed: {e}")

    with st.expander("🔀 Move Model to Another Category"):
        st.write("Instantly reorganize your catalog. Select a model and send it to a different category.")
        move_col1, move_col2, move_col3 = st.columns([2, 2, 1])
        with move_col1:
            all_known_models = sorted(list(unique_models))
            model_to_move = st.selectbox("Select model:", ["-- Select --"] + all_known_models, key="move_mod")
        with move_col2:
            target_cat = st.selectbox("Select new category:", ["-- Select --"] + categories, key="move_cat")
        with move_col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Move", use_container_width=True, type="primary"):
                if model_to_move != "-- Select --" and target_cat != "-- Select --":
                    for c in list(st.session_state.cloud_models.keys()):
                        if model_to_move in st.session_state.cloud_models[c]:
                            st.session_state.cloud_models[c].remove(model_to_move)
                    if target_cat not in st.session_state.cloud_models:
                        st.session_state.cloud_models[target_cat] = set()
                    st.session_state.cloud_models[target_cat].add(model_to_move)

                    if st.session_state.sh:
                        try:
                            dict_sheet = st.session_state.sh.worksheet("Dictionary")
                            dict_sheet.clear()
                            dict_upload = [["Category", "Model"]]
                            for c, models_in_cat in st.session_state.cloud_models.items():
                                for m_val in models_in_cat:
                                    dict_upload.append([c, m_val])
                            dict_sheet.update(values=dict_upload, range_name="A1")
                            st.success(f"✅ Model '{model_to_move}' moved to '{target_cat}'!")
                        except Exception:
                            st.toast("⚠️ Cloud sync delayed. Saved locally.")
                    st.rerun()
                else:
                    st.warning("Select both model and destination.")

    with st.expander("❌ Delete a Specific Model"):
        st.write("Select a model to permanently remove from memory:")
        del_col1, del_col2 = st.columns([3, 1])
        with del_col1:
            all_known_models = sorted(list(unique_models))
            model_to_delete = st.selectbox("Select model:", ["-- Select --"] + all_known_models, label_visibility="collapsed", key="del_mod")
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
                                tmp = file + ".tmp"
                                with open(tmp, "w") as f: json.dump(other_data, f)
                                os.replace(tmp, file)
                        except: pass

                    for c in list(st.session_state.cloud_models.keys()):
                        if model_to_delete in st.session_state.cloud_models[c]:
                            st.session_state.cloud_models[c].remove(model_to_delete)

                    if st.session_state.sh:
                        try:
                            dict_sheet = st.session_state.sh.worksheet("Dictionary")
                            dict_sheet.clear()
                            dict_upload = [["Category", "Model"]]
                            for c, models_in_cat in st.session_state.cloud_models.items():
                                for m_val in models_in_cat:
                                    dict_upload.append([c, m_val])
                            dict_sheet.update(values=dict_upload, range_name="A1")
                            st.success(f"✅ '{model_to_delete}' completely erased from counts and dictionary!")
                        except Exception as e:
                            st.toast("⚠️ Cloud sync delayed. Saved locally.")
                    st.rerun()

    with st.expander("🔄 Reset All Counts to Zero (Fresh Count)"):
        st.write("Start a fresh physical inventory count. This sets all quantities to 0 but **keeps your models, categories, and cloud history perfectly intact.**")
        
        confirm_zero = st.checkbox("Are you sure? Check this box to unlock the reset button.")
        
        if st.button("Reset All Counts", use_container_width=True, type="primary", disabled=not confirm_zero):
            st.session_state.data = {}
            st.session_state.history = [] 
            
            for file in glob.glob("inventory_data_*.json") + glob.glob("inventory_history_*.json"):
                try: os.remove(file)
                except: pass
            
            save_local_db()
            
            if st.session_state.sh:
                try:
                    audit_sheet = st.session_state.sh.worksheet("Audit Log")
                    full_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
                    audit_sheet.append_row([f"[{full_timestamp}] 🔄 SYSTEM: {st.session_state.current_user} RESET ALL INVENTORY COUNTS TO ZERO."])
                except Exception:
                    pass
                    
            st.rerun()

    with st.expander("👤 Manage Worker Accounts"):
        st.write("Add new worker logins or remove old ones.")
        acc_col1, acc_col2 = st.columns(2)
        
        with acc_col1:
            st.markdown("**➕ Add New Account**")
            new_u = st.text_input("New Username:", key="new_u")
            new_p = st.text_input("New Password:", type="password", key="new_p")
            if st.button("Create Account", type="primary"):
                if new_u and new_p:
                    if new_u in auth_db:
                        st.warning("User already exists!")
                    else:
                        auth_db[new_u] = new_p
                        with open(USER_FILE, "w") as f:
                            json.dump(auth_db, f)
                        st.success(f"Account '{new_u}' created!")
                        st.rerun()
                else:
                    st.warning("Enter both a username and password.")
                    
        with acc_col2:
            st.markdown("**❌ Remove Account**")
            removable_users = [u for u in auth_db.keys() if u != "Admin"]
            del_u = st.selectbox("Select User to Remove:", ["-- Select --"] + removable_users)
            if st.button("Delete Account"):
                if del_u != "-- Select --":
                    del auth_db[del_u]
                    with open(USER_FILE, "w") as f:
                        json.dump(auth_db, f)
                    st.success(f"Account '{del_u}' deleted!")
                    st.rerun()

    with st.expander("🗑️ Wipe Everything"):
        st.warning("🚨 DANGER: This permanently erases all your models and counts locally.")
        st.write("To unlock the delete button, type **WIPE EVERYTHING** below:")
        confirm_wipe = st.text_input("Confirmation text", label_visibility="collapsed")
        if st.button("Yes, Wipe My Data", use_container_width=True, type="primary", disabled=(confirm_wipe != "WIPE EVERYTHING")):
            st.session_state.data = {}
            st.session_state.history = [] 
            for file in glob.glob("inventory_data_*.json") + glob.glob("inventory_history_*.json"):
                try: os.remove(file)
                except: pass
            save_local_db()
            st.rerun()
