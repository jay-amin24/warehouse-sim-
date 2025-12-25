%%writefile app.py
# app.py
import streamlit as st
import pandas as pd
import time
import random
import sqlite3
import threading
from io import BytesIO
from datetime import datetime
from warehouse import Warehouse, Pallet

# ------------------- Configurable Visual Slots -------------------
CONVEYOR_SLOTS = 3
RGV_SLOTS = 3

# ------------------- Database Setup (WAL + cached connection) -------------------
@st.cache_resource
def get_connection():
    # Single connection reused across reruns; WAL for better concurrency
    conn = sqlite3.connect("warehouse.db", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")        # readers/writer concurrency via WAL [single writer]
    conn.execute("PRAGMA synchronous=NORMAL;")      # good balance of safety/perf for WAL
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

conn = get_connection()
db_lock = threading.Lock()

with db_lock:
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS pallet_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pallet_id TEXT,
        rfid TEXT,
        weight REAL,
        stage TEXT,
        location TEXT,
        timestamp TEXT
    )
    ''')
    conn.commit()

def insert_movement_log(pallet_id, rfid, weight, stage, location=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        conn.execute(
            '''INSERT INTO pallet_movements (pallet_id, rfid, weight, stage, location, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (pallet_id, rfid, weight, stage, location, timestamp)
        )
        conn.commit()

def query_rfid(rfid):
    with db_lock:
        return pd.read_sql_query(
            "SELECT * FROM pallet_movements WHERE rfid = ? ORDER BY id DESC",
            conn, params=(rfid,)
        )

def query_pallet_id(pid):
    with db_lock:
        return pd.read_sql_query(
            "SELECT * FROM pallet_movements WHERE pallet_id = ? ORDER BY id DESC",
            conn, params=(pid,)
        )

def query_all(limit=200):
    with db_lock:
        return pd.read_sql_query(
            f"SELECT * FROM pallet_movements ORDER BY id DESC LIMIT {int(limit)}", conn
        )

def query_log_all():
    with db_lock:
        return pd.read_sql_query("SELECT * FROM pallet_movements", conn)

# Warehouse Setup
ROWS, COLS, LAYERS = 3, 3, 2
TOLERANCE = 25
if "warehouse" not in st.session_state:
    st.session_state.warehouse = Warehouse(ROWS, COLS, LAYERS, TOLERANCE)
warehouse = st.session_state.warehouse

st.title("🏭 Automated Smart Warehouse Simulation")
st.caption("ASRS + RGV + Conveyor • RFID • Weight tolerance ±25 kg • SQLite logging")

#Pallet Generation
num_pallets = st.number_input("Number of inbound pallets", min_value=1, max_value=20, value=5)
if st.button("Generate Pallets"):
    st.session_state.pallets = []
    for i in range(num_pallets):
        weight = round(random.uniform(375, 425), 1)  # 400 ±25
        pallet_id = f"P{i+1}"
        rfid_code = f"RFID-{random.randint(10000, 99999)}"
        p = Pallet(pallet_id=pallet_id, weight=weight, rfid=rfid_code)
        st.session_state.pallets.append(p)
    st.success(f"Generated {num_pallets} inbound pallets with RFID codes.")

# Layer Selector (UI is 1-based)
layer_display = st.selectbox(
    "Select ASRS Layer to View (1-based)",
    options=list(range(1, warehouse.capacity['layers'] + 1)),
    index=0
)
layer_idx = layer_display - 1  # convert to 0-based for internal use

#Grid Drawing with Animation
def draw_grid(pallet_positions, show_layer_idx=0, highlight=None):
    """pallet_positions: dict[pid] -> {stage,index,row,col,layer,weight,rfid} (0-based row/col/layer)"""
    inbound_list = []
    conveyor = ["⬜"] * CONVEYOR_SLOTS
    rgv = ["⬜"] * RGV_SLOTS
    rows = warehouse.capacity["rows"]
    cols = warehouse.capacity["columns"]
    asrs = [["⬜" for _ in range(cols)] for _ in range(rows)]

    for p, pos in pallet_positions.items():
        # color coding by weight/stage
        if pos["stage"] in ["asrs", "conveyor", "rgv", "inbound"]:
            if pos["weight"] < 375 or pos["weight"] > 425:
                color_emoji = "🟨"  # outside spec (shouldn’t happen if inbound gate works)
            else:
                color_emoji = "🟩"
        else:
            color_emoji = "🟥"  # manual

        if highlight == p:
            color_emoji = "💚"

        display_text = f"{color_emoji}{p}"

        if pos["stage"] in ["manual", "inbound"]:
            inbound_list.append(display_text)
        elif pos["stage"] == "conveyor":
            idx = max(0, min(pos["index"], CONVEYOR_SLOTS - 1))
            conveyor[idx] = display_text
        elif pos["stage"] == "rgv":
            idx = max(0, min(pos["index"], RGV_SLOTS - 1))
            rgv[idx] = display_text
        elif pos["stage"] == "asrs":
            r, c, l = pos["row"], pos["col"], pos["layer"]
            if l == show_layer_idx:
                if 0 <= r < rows and 0 <= c < cols:
                    asrs[r][c] = display_text

    st.text(f"Inbound: {' '.join(inbound_list) if inbound_list else '⬜'}")
    st.text(f"Conveyor: {' '.join(conveyor)}")
    st.text(f"RGV:      {' '.join(rgv)}")
    st.text(f"ASRS Layer {show_layer_idx + 1}:")
    for row in asrs:
        st.text(" ".join(row))

# KPI Dashboard
def update_kpi():
    with db_lock:
        df = pd.read_sql_query("SELECT * FROM pallet_movements", conn)

    total = len(df)
    stored = int((df['stage'] == "Stored").sum())
    manual = int(df['stage'].fillna("").str.contains("Manual", na=False).sum())

    st.subheader("📊 KPI Dashboard")
    st.metric("Total Pallets Processed", total)
    st.metric("Stored Pallets", stored)
    st.metric("Manual Exceptions", manual)

    if total > 0:
        st.bar_chart(pd.DataFrame({"Stored": [stored], "Manual": [manual]}), use_container_width=True)

#  Animated Simulation
if st.button("▶ Run Simulation"):
    if not hasattr(st.session_state, "pallets") or not st.session_state.pallets:
        st.warning("Generate pallets first!")
    else:
        movement_placeholder = st.empty()
        grid_placeholder = st.empty()

        pallet_positions = {}
        # Build a map of id -> pallet object (handy for later if needed)
        pallet_map = {p.pallet_id: p for p in st.session_state.pallets}

        for pallet in st.session_state.pallets:
            pallet_positions[pallet.pallet_id] = {
                "stage": "inbound",
                "index": 0,
                "row": None,
                "col": None,
                "layer": None,
                "weight": pallet.weight,
                "rfid": pallet.rfid
            }

        finished = False
        while not finished:
            finished = True
            for pallet_id, pos in list(pallet_positions.items()):
                if pos["stage"] in ["asrs", "manual"]:
                    continue
                finished = False
                highlight = None

                # Inbound weight check (gate)
                if pos["stage"] == "inbound":
                    highlight = pallet_id
                    with grid_placeholder.container():
                        draw_grid(pallet_positions, show_layer_idx=layer_idx, highlight=highlight)
                    time.sleep(0.4)
                    if abs(pos["weight"] - 400) > TOLERANCE:
                        pos["stage"] = "manual"
                        insert_movement_log(pallet_id, pos["rfid"], pos["weight"], "Manual Packing")
                        movement_placeholder.markdown(f"❌ Pallet {pallet_id} → Manual Packing")
                    else:
                        pos["stage"] = "conveyor"
                        pos["index"] = 0
                        insert_movement_log(pallet_id, pos["rfid"], pos["weight"], "Inbound OK")

                # Conveyor movement
                elif pos["stage"] == "conveyor":
                    if pos["index"] < CONVEYOR_SLOTS - 1:
                        pos["index"] += 1
                        highlight = pallet_id
                        with grid_placeholder.container():
                            draw_grid(pallet_positions, show_layer_idx=layer_idx, highlight=highlight)
                        time.sleep(random.uniform(0.25, 0.6))
                    else:
                        pos["stage"] = "rgv"
                        pos["index"] = 0
                        insert_movement_log(pallet_id, pos["rfid"], pos["weight"], "Conveyor OK")

                # RGV movement
                elif pos["stage"] == "rgv":
                    if pos["index"] < RGV_SLOTS - 1:
                        pos["index"] += 1
                        highlight = pallet_id
                        with grid_placeholder.container():
                            draw_grid(pallet_positions, show_layer_idx=layer_idx, highlight=highlight)
                        time.sleep(random.uniform(0.25, 0.6))
                    else:
                        loc = warehouse.assign_location()  # returns 0-based (r,c,l)
                        if loc is None:
                            pos["stage"] = "manual"
                            insert_movement_log(pallet_id, pos["rfid"], pos["weight"], "Manual (No Space)")
                            movement_placeholder.markdown(f"❌ Pallet {pallet_id} → Manual (No ASRS space)")
                        else:
                            r, c, l = loc
                            pos["stage"] = "asrs"
                            pos["row"], pos["col"], pos["layer"] = r, c, l
                            # human-readable 1-based in DB log
                            insert_movement_log(
                                pallet_id, pos["rfid"], pos["weight"], "Stored",
                                f"Row {r+1}, Col {c+1}, Layer {l+1}"
                            )
                            with grid_placeholder.container():
                                draw_grid(pallet_positions, show_layer_idx=layer_idx, highlight=pallet_id)
                            time.sleep(0.7)

            with grid_placeholder.container():
                draw_grid(pallet_positions, show_layer_idx=layer_idx)

            update_kpi()

        st.success("✅ Simulation Complete!")

# RFID & Pallet Search
st.subheader("🔍 Search Pallet")
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    rfid_input = st.text_input(
        "RFID (e.g., RFID-12345)",
        key="rfid_input",
        placeholder="RFID-12345"
    )
with col2:
    # quick pick by known pallet IDs (from current session if generated)
    pallet_ids = [p.pallet_id for p in st.session_state.get("pallets", [])]
    pallet_pick = st.selectbox(
        "Pallet ID (from this session)",
        options=["—"] + pallet_ids,
        index=0
    )
with col3:
    go = st.button("🔍 Search")

if go:
    if rfid_input.strip():
        df_query = query_rfid(rfid_input.strip())
        if df_query.empty:
            st.info("No pallet found with this RFID.")
        else:
            st.success(f"✅ Found pallet(s) with RFID `{rfid_input.strip()}`")
            st.dataframe(df_query, use_container_width=True)
    elif pallet_pick != "—":
        df_query = query_pallet_id(pallet_pick)
        if df_query.empty:
            st.info("No pallet found with this Pallet ID.")
        else:
            st.success(f"✅ Found pallet `{pallet_pick}`")
            st.dataframe(df_query, use_container_width=True)
    else:
        st.warning("Enter an RFID or choose a Pallet ID.")

# Show All Recent
if st.button("📜 Show All Recent Movements"):
    df_all = query_all(limit=200)
    st.dataframe(df_all, use_container_width=True)

# Export DB Log

st.subheader("⬇️ Download Movement Log from DB")
df_log = pd.read_sql_query("SELECT * FROM pallet_movements", conn)
st.download_button(
    "Download CSV",
    data=df_log.to_csv(index=False).encode("utf-8"),
    file_name="warehouse_movement_log.csv",
    mime="text/csv"
)
