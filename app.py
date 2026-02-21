import streamlit as st
import pandas as pd
from datetime import datetime

# --- Page Setup ---
st.set_page_config(page_title="Warehouse Inventory", page_icon="📦", layout="centered")

# --- Authentication (The Bouncer) ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 App Locked")
    st.warning("Please enter the password to access the inventory.")
    
    # Use type="password" so it hides the typing with dots
    pwd = st.text_input("Password", type="password")
    
    if st.button("Login"):
        # Look in the secure vault for the password. 
        # (It defaults to "blackbelt" only when testing locally on your computer)
        correct_password = st.secrets.get("app_password", "blackbelt")
        
        if pwd == correct_password: 
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password. Access Denied.")
            
    # This crucial command stops the rest of the code from running!
    st.stop() 

# --- Memory Setup (Session State) ---
# This acts exactly like LocalStorage did in the HTML version
if 'data' not in st.session_state:
    st.session_state.data = {}
if 'history' not in st.session_state:
    st.session_state.history = []

# --- Header ---
st.title("📦 Warehouse Inventory")
st.markdown("---")

# --- Input Area ---
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    model = st.text_input("Model Number").upper().strip()
with col2:
    qty = st.number_input("Quantity", min_value=1, step=1, value=1)
with col3:
    loc = st.selectbox("Location", ["Warehouse", "Assembly", "Suspect"])

# --- Math & Logic Functions ---
def modify_inventory(direction):
    if not model:
        st.error("Please enter a Model Number.")
        return
        
    key = f"{model}|{loc}"
    if key not in st.session_state.data:
        st.session_state.data[key] = 0
        
    # Do the math
    change = qty if direction == "add" else -qty
    st.session_state.data[key] += change
    
    # Save to history for Undo button
    action_word = "Added" if direction == "add" else "Removed"
    st.session_state.history.append({
        "action": action_word,
        "model": model,
        "qty": qty,
        "loc": loc,
        "key": key,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })
    
    # Show instant flash message
    if direction == "add":
        st.success(f"✓ {action_word} {qty} {model} ({loc}) [Total: {st.session_state.data[key]}]")
    else:
        st.warning(f"⚠ {action_word} {qty} {model} ({loc}) [Total: {st.session_state.data[key]}]")

def undo_last():
    if not st.session_state.history:
        st.warning("Nothing to undo!")
        return
        
    last = st.session_state.history.pop()
    change = last["qty"] if last["action"] == "Added" else -last["qty"]
    st.session_state.data[last["key"]] -= change
    st.info(f"↺ Undid last action for {last['model']}")

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

# Convert our dictionary data into a clean table (Pandas DataFrame)
report_rows = []
unique_models = sorted(list(set([k.split("|")[0] for k in st.session_state.data.keys()])))

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
    
    # Search Bar
    search = st.text_input("🔍 Search Models to Filter:")
    if search:
        df = df[df["Model"].str.contains(search.upper())]
        
    # Draw the table
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Excel Download Button (with Date & Time)
    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    csv = df.to_csv(index=False).encode('utf-8')
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
    if st.session_state.history:
        for item in reversed(st.session_state.history[-10:]):
            st.text(f"[{item['timestamp']}] {item['action']} {item['qty']} x {item['model']} ({item['loc']})")
    else:
        st.text("No history yet.")

# --- Reset Button ---
st.markdown("<br><br>", unsafe_allow_html=True)
if st.button("⚠️ Start New Day (Clear All Data)"):
    st.session_state.data = {}
    st.session_state.history = []
    st.rerun()
