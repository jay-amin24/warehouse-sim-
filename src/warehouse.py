# warehouse.py
%%writefile warehouse.py
class Pallet:
    def __init__(self, pallet_id, weight, rfid=None):
        self.pallet_id = pallet_id
        self.weight = weight
        self.status = "Pending"
        self.location = None  # (row, col, layer) 0-based
        self.rfid = rfid if rfid else f"RFID-{pallet_id}"  # auto-generate if not given

class Warehouse:
    def __init__(self, rows=3, cols=3, layers=2, tolerance=25):
        self.tolerance = tolerance
        self.capacity = {"rows": rows, "columns": cols, "layers": layers}
        self.occupied = set()  # set of (r, c, l) 0-based
        self.movement_log = []  # list[dict] (not used; DB handles persistence)

    def assign_location(self):
        """Return first free (row, col, layer) as 0-based tuple or None if full."""
        R = self.capacity["rows"]
        C = self.capacity["columns"]
        L = self.capacity["layers"]
        for l in range(L):  # layer-first
            for r in range(R):
                for c in range(C):
                    pos = (r, c, l)
                    if pos not in self.occupied:
                        self.occupied.add(pos)
                        return pos
        return None

