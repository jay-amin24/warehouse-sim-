# app.py (Smart Warehouse Simulation with Animated Movement)
import streamlit as st
import pandas as pd
import time
import random
import sqlite3
from datetime import datetime
from warehouse import Warehouse, Pallet

# ------------------- Database Setup -------------------
conn = sqlite3.connect("warehouse.db", check_same_thread=False)
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
    c.execute('''
        INSERT INTO pallet_movements (pallet_id, rfid, weight, stage, location, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (pallet_id, rfid, weight, stage, location, timestamp))
    conn.commit()

def query_rfid(rfid):
    df = pd.read_sql_query(f"SELECT * FROM pallet_movements WHERE rfid='{rfid}'", conn)
    return df

# ------------------- Warehouse Setup -------------------
ROWS, COLS, LAYERS = 3, 3, 2
TOLERANCE = 25

if "warehouse" not in st.session_state:
    st.session_state.warehouse = Warehouse(ROWS, COLS, LAYERS, TOLERANCE)

warehouse = st.session_state.warehouse

st.title("🏭 Animated Smart Warehouse Simulation")
st.markdown(
    "Concurrent multi-pallet animation with ASRS stacking, RFID, weight validation, KPI, and SQLite logging"
)

# ------------------- Pallet Generation -------------------
num_pallets = st.number_input("Number of inbound pallets", min_value=1, max_value=10, value=3)
if st.button("Generate Pallets"):
    st.session_state.pallets = []
    for i in range(num_pallets):
        weight = round(random.uniform(375, 425), 1)
        pallet_id = f"P{i+1}"
        rfid_code = f"RFID-{random.randint(10000,99999)}"
        pallet = Pallet(pallet_id=pallet_id, weight=weight)
        pallet.rfid = rfid_code
        st.session_state.pallets.append(pallet)
    st.success(f"Generated {num_pallets} inbound pallets with RFID codes.")

# ------------------- Layer Selector -------------------
layer_selected = st.selectbox("Select ASRS Layer to View", options=list(range(1, warehouse.capacity['layers']+1)), index=0)

# ------------------- Grid Drawing with Animation -------------------
def draw_grid(pallet_positions, show_layer=1, highlight=None):
    inbound_list = []
    conveyor = ["⬜"] * 3
    rgv = ["⬜"] * 3
    asrs = [["⬜"] * warehouse.capacity["columns"] for _ in range(warehouse.capacity["rows"])]

    for p, pos in pallet_positions.items():
        # color coding by weight/stage
        if pos["stage"] in ["asrs", "conveyor", "rgv", "inbound"]:
            if pos["weight"] < 380 or pos["weight"] > 420:
                color_emoji = "🟨"  # borderline
            else:
                color_emoji = "🟩"  # normal
        elif pos["stage"] == "manual":
            color_emoji = "🟥"

        # temporary highlight (for animation)
        if highlight == p:
            color_emoji = "💚"

        display_text = f"{color_emoji}{p}"

        if pos["stage"] == "manual":
            inbound_list.append(display_text)
        elif pos["stage"] == "inbound":
            inbound_list.append(display_text)
        elif pos["stage"] == "conveyor":
            conveyor[pos["index"]] = display_text
        elif pos["stage"] == "rgv":
            rgv[pos["index"]] = display_text
        elif pos["stage"] == "asrs":
            row, col, layer = pos["row"], pos["col"], pos["layer"]
            if layer == show_layer:
                asrs[row][col] = display_text

    st.text(f"Inbound: {' '.join(inbound_list) if inbound_list else '⬜'}")
    st.text(f"Conveyor: {' '.join(conveyor)}")
    st.text(f"RGV:      {' '.join(rgv)}")
    st.text(f"ASRS Layer {show_layer}:")
    for row in asrs:
        st.text(" ".join(row))

# ------------------- KPI Dashboard -------------------
def update_kpi():
    df = pd.read_sql_query("SELECT * FROM pallet_movements", conn)
    total = len(df)
    stored = len(df[df['stage'] == "Stored"])
    manual = len(df[df['stage'].str.contains("Manual")])
    st.subheader("📊 KPI Dashboard")
    st.metric("Total Pallets Processed", total)
    st.metric("Stored Pallets", stored)
    st.metric("Manual Exceptions", manual)
    if total > 0:
        st.bar_chart(pd.DataFrame({"Stored": [stored], "Manual": [manual]}))

# ------------------- Animated Simulation -------------------
if st.button("Run Simulation"):
    if not hasattr(st.session_state, "pallets") or not st.session_state.pallets:
        st.warning("Generate pallets first!")
    else:
        movement_placeholder = st.empty()
        grid_placeholder = st.empty()
        finished = False

        pallet_positions = {}
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

        while not finished:
            finished = True
            for pallet_id, pos in pallet_positions.items():
                if pos["stage"] in ["asrs", "manual"]:
                    continue
                finished = False

                highlight = None

                # Inbound weight check
                if pos["stage"] == "inbound":
                    highlight = pallet_id
                    draw_grid(pallet_positions, layer_selected, highlight=highlight)
                    time.sleep(0.5)
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
                    if pos["index"] < 2:
                        pos["index"] += 1
                        highlight = pallet_id
                        draw_grid(pallet_positions, layer_selected, highlight=highlight)
                        time.sleep(random.uniform(0.3, 0.8))
                    else:
                        pos["stage"] = "rgv"
                        pos["index"] = 0
                        insert_movement_log(pallet_id, pos["rfid"], pos["weight"], "Conveyor OK")

                # RGV movement
                elif pos["stage"] == "rgv":
                    if pos["index"] < 2:
                        pos["index"] += 1
                        highlight = pallet_id
                        draw_grid(pallet_positions, layer_selected, highlight=highlight)
                        time.sleep(random.uniform(0.3, 0.8))
                    else:
                        row, col, layer = warehouse.assign_location()
                        if row is None:
                            pos["stage"] = "manual"
                            insert_movement_log(pallet_id, pos["rfid"], pos["weight"], "Manual (No Space)")
                            movement_placeholder.markdown(f"❌ Pallet {pallet_id} → Manual (No ASRS space)")
                        else:
                            pos["stage"] = "asrs"
                            pos["row"], pos["col"], pos["layer"] = row, col, layer
                            insert_movement_log(pallet_id, pos["rfid"], pos["weight"], "Stored",
                                                f"Row {row}, Col {col}, Layer {layer}")
                            # highlight ASRS landing
                            draw_grid(pallet_positions, layer_selected, highlight=pallet_id)
                            time.sleep(0.8)

            draw_grid(pallet_positions, layer_selected)
            update_kpi()

        st.success("✅ Simulation Complete!")

# ------------------- RFID Search -------------------
st.subheader("🔍 Search Pallet by RFID")
rfid_input = st.text_input("Enter RFID (e.g., RFID-12345)")
if st.button("Search RFID"):
    if rfid_input.strip() != "":
        df_query = query_rfid(rfid_input.strip())
        if df_query.empty:
            st.info("No pallet found with this RFID.")
        else:
            st.dataframe(df_query)
    else:
        st.warning("Enter a valid RFID.")

# ------------------- Export DB Log -------------------
st.subheader("⬇️ Download Movement Log from DB")
df_log = pd.read_sql_query("SELECT * FROM pallet_movements", conn)
st.download_button(
    "Download CSV",
    data=df_log.to_csv(index=False).encode("utf-8"),
    file_name="warehouse_movement_log.csv",
    mime="text/csv"
)

