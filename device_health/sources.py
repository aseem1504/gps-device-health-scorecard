"""Where pings come from.

HttpPingSource talks to a telematics API shaped like the one the original code used
(set GPS_API_BASE). SimulatedPingSource serves generated data so everything runs offline.
"""
import json
import os
import urllib.request

import numpy as np
import pandas as pd

from . import simulate


class HttpPingSource:
    def __init__(self, base=None):
        self.base = base or os.environ.get('GPS_API_BASE', 'http://localhost:8080')

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            return json.load(r)

    def pings(self, vid, start, end):
        q = f"vehicleIds={vid}&fromTime={int(start)}&toTime={int(end)}&sortOrder=&timeCondition="
        try:
            lc = pd.DataFrame(self._get(f"/gps/vehicles?{q}")['data'][str(vid)])
        except Exception:
            lc = pd.DataFrame()
        try:
            hb = pd.DataFrame(self._get(f"/heartbeat/list?{q}")['data'][str(vid)])
        except Exception:
            hb = pd.DataFrame()
        return lc, hb

    def last_ping(self, vid):
        """Latest of the last location ping and the last heartbeat (find_last_ping in the original)."""
        last_loc = last_hb = 0
        try:
            last_loc = self._get(f"/gps/top?vehicleIds={vid}&sortOrder=desc")['data'][str(vid)]['time']
        except Exception:
            pass
        try:
            last_hb = self._get(f"/heartbeat/top?vehicleIds={vid}&sortOrder=desc")['data'][str(vid)]['created'] / 1000
        except Exception:
            pass
        return max(last_loc, last_hb)


class SimulatedPingSource:
    def __init__(self, n_vehicles=150, days=5, seed=8, start_day=1_600_041_600):
        self.fleet = simulate.fleet_table(n_vehicles, seed)
        self.days = days
        self.start_day = start_day
        self._rng = np.random.default_rng(seed)
        self._cache = {}

    def _day(self, vid, day_start):
        key = (vid, day_start)
        if key not in self._cache:
            row = self.fleet[self.fleet.vehicle_id == vid].iloc[0]
            prev = self._cache.get((vid, day_start - 86400))
            start_loc = prev[0].location.iloc[-1] if prev is not None and len(prev[0]) else None
            self._cache[key] = simulate.vehicle_day(self._rng, row, day_start, start_loc)
        return self._cache[key]

    def pings(self, vid, start, end):
        first = int(start) - int(start) % 86400
        days = [self._day(vid, d) for d in range(first, int(end), 86400)]
        lc = pd.concat([d[0] for d in days], ignore_index=True)
        hb = pd.concat([d[1] for d in days], ignore_index=True)
        lc = lc[(lc.time >= start) & (lc.time < end)]
        hb = hb[(hb.created / 1000 >= start) & (hb.created / 1000 < end)] if len(hb) else hb
        return lc, hb

    def last_ping(self, vid):
        return self.start_day + self.days * 86400 - 100
