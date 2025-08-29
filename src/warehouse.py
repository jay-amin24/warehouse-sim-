import random
import pandas as pd
import time
from datetime import datetime

class Pallet:
    def __init__(self, pallet_id, weight):
        self.pallet_id = pallet_id
        self.weight = weight
        self.status = "Pending"
        self.location = None

class Warehouse:
    def __init__(self, tolerance=25):
        self.tolerance = tolerance
        self.logs = []
        self.capacity = {"rows": 5, "columns": 4, "layers": 3}
        self.occupied = set()

    def log_step(self, pallet, step, location=None):
        """Helper: log + print"""
        entry = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Pallet ID": pallet.pallet_id,
            "Weight (kg)": pallet.weight,
            "Step": step,
            "Status": pallet.status,
            "Location": str(location) if location else None
        }
        self.logs.append(entry)
        print(f"[{entry['Timestamp']}] Pallet {pallet.pallet_id} → {step} | Status: {pallet.status} | Location: {entry['Location']}")

    def check_weight(self, pallet):
        if abs(pallet.weight - 400) <= self.tolerance:
            pallet.status = "Accepted"
            return True
        else:
            pallet.status = "Rejected - Manual Packing"
            return False

    def assign_location(self, pallet):
        for r in range(1, self.capacity["rows"]+1):
            for c in range(1, self.capacity["columns"]+1):
                for l in range(1, self.capacity["layers"]+1):
                    pos = (r, c, l)
                    if pos not in self.occupied:
                        self.occupied.add(pos)
                        pallet.location = pos
                        return pos
        return None

    def process_pallet(self, pallet):
        # Inbound
        self.log_step(pallet, "Inbound")
        time.sleep(0.5)

        if self.check_weight(pallet):
            self.log_step(pallet, "Weighing")
            time.sleep(0.5)
            self.log_step(pallet, "RGV Loading")
            time.sleep(0.5)
            self.log_step(pallet, "Conveyor Transfer")
            time.sleep(0.5)
            self.log_step(pallet, "ASRS Lift")
            time.sleep(0.5)

            loc = self.assign_location(pallet)
            if loc:
                pallet.status = "Stored"
                self.log_step(pallet, "Stored in ASRS", loc)
            else:
                pallet.status = "Rejected - Warehouse Full"
                self.log_step(pallet, "Rejected", None)
        else:
            self.log_step(pallet, "Manual Packing")

    def export_to_excel(self, filename="warehouse_log.xlsx"):
        df = pd.DataFrame(self.logs)
        df.to_excel(filename, index=False)
        print(f"\n✅ Logs exported to {filename}")


# ---------------- DEMO RUN ----------------
if __name__ == "__main__":
    wh = Warehouse()

    for i in range(1, 6):  # 5 pallets demo
        weight = random.randint(380, 420)
        pallet = Pallet(f"P{i:03}", weight)
        wh.process_pallet(pallet)
        print("-"*60)

    wh.export_to_excel()
