"""Synthetic fleet with known device problems, so the scorecard can be checked against the truth.

Nothing here is real. Device models are fictional (MODEL_A ... MODEL_E) on purpose: the
quality profiles below are made up, and pinning them on real hardware names would be unfair.

Each vehicle gets:
  * a device model with its own quirks (ping interval, GPS jumps, late uploads, dropped pings)
  * a SIM network (NET_1 / NET_2), where NET_2 has more outages
  * an installer, a heartbeat channel or not, and sometimes a wiring fault
"""
import numpy as np
import pandas as pd

# Devices ping every 10 s while driving and every 30 s when parked (what the original
# expected_run / expected_stop metrics assume). `slow` stretches both.
MODELS = {   # slow, jump_rate, delay_mean_s, drop_rate, has_heartbeat
    'MODEL_A': (1.0, 0.0003, 15, 0.02, True),
    'MODEL_B': (1.0, 0.0005, 20, 0.04, False),
    'MODEL_C': (1.0, 0.0060, 25, 0.05, False),   # jumpy GPS chip
    'MODEL_D': (2.0, 0.0005, 240, 0.08, False),  # pings less often, uploads late
    'MODEL_E': (1.0, 0.0004, 18, 0.25, True),    # drops a lot of pings
}
NETWORKS = {'NET_1': 0.03, 'NET_2': 0.12}   # chance per hour that the network drops out
INSTALLERS = [f'INSTALLER_{i:02d}' for i in range(1, 13)]


def fleet_table(n=150, seed=8):
    rng = np.random.default_rng(seed)
    v = pd.DataFrame({
        'vehicle_id': 500000 + np.arange(n),
        'model_name': rng.choice(list(MODELS), n, p=[.3, .25, .15, .15, .15]),
        'installer': rng.choice(INSTALLERS, n),
    })
    # some installers mostly fit NET_2 SIMs (the pattern the original notebook went looking for)
    heavy = set(INSTALLERS[:3])
    v['network'] = [rng.choice(['NET_1', 'NET_2'], p=[.2, .8] if i in heavy else [.75, .25]) for i in v.installer]
    v['wiring_fault'] = rng.choice(['none', 'wire_loose', 'intentional_wire_cut', 'charge_to_ign'], n, p=[.8, .1, .05, .05])
    v['has_heartbeat'] = v.model_name.map(lambda m: MODELS[m][4])
    return v


def vehicle_day(rng, row, day_start, start_loc=None):
    slow, jump_rate, delay_mean, drop_rate, has_hb = MODELS[row.model_name]
    # alternate driving and parked blocks; ping faster while driving
    times, driving = [], []
    t = 0.0
    while t < 86400:
        drive = rng.random() < 0.5
        block = rng.uniform(30, 180) * 60
        step = (10 if drive else 30) * slow
        k = np.arange(t, min(t + block, 86400), step)
        times.append(k)
        driving.append(np.full(len(k), drive))
        t += block
    t = day_start + np.concatenate(times).astype(int)
    driving = np.concatenate(driving)
    n = len(t)
    dt_ = np.diff(t, prepend=t[0])
    lon, lat = start_loc if start_loc is not None else (rng.uniform(72, 86), rng.uniform(18, 28))
    heading = rng.uniform(0, 6.28)
    speed = np.where(driving, rng.normal(45, 8, n).clip(10, 80), 0.0)
    locs = []
    for s_, step in zip(speed, dt_):
        heading += rng.normal(0, 0.02)
        d = s_ / 3.6 * step / 111_000
        lon += d * np.cos(heading)
        lat += d * np.sin(heading)
        if rng.random() < jump_rate:   # GPS fix lands kilometres away for one ping
            locs.append([lon + rng.normal(0, 0.03), lat + rng.normal(0, 0.03)])
        else:
            locs.append([lon + rng.normal(0, 2e-5), lat + rng.normal(0, 2e-5)])
    keep = rng.random(n) > drop_rate
    # network outages: whole hours with nothing received
    for h in range(24):
        if rng.random() < NETWORKS[row.network]:
            a = day_start + h * 3600
            keep[(t >= a) & (t < a + rng.integers(60, 180) * 60)] = False
    created = (t + rng.exponential(delay_mean, n)) * 1000
    ign = driving | (rng.random(n) < 0.03)
    charge = np.ones(n, bool)
    if row.wiring_fault == 'wire_loose':
        charge[rng.choice(n, 10, replace=False)] = False
    elif row.wiring_fault == 'intentional_wire_cut':
        idx = np.where(driving)[0]
        if len(idx) > 100:
            charge[idx[20:90]] = False
    elif row.wiring_fault == 'charge_to_ign':
        charge = ign.copy()
    volt = np.where(charge, 95, 50.0)
    lc = pd.DataFrame({'vehicleId': row.vehicle_id, 'time': t, 'created': created, 'location': locs,
                       'speed': speed.round(1), 'usedSat': rng.integers(4, 14, n),
                       'gsmPct': (rng.normal(72 if row.network == 'NET_1' else 58, 12, n)).clip(0, 100).round()})[keep]
    if not has_hb:
        lc['chargeOn'], lc['ignOn'], lc['voltPct'] = charge[keep], ign[keep], volt[keep]
        return lc.reset_index(drop=True), pd.DataFrame()
    hb_t = day_start + np.arange(0, 86400, 120)
    hk = np.interp(hb_t, t, keep.astype(float)) > 0.5
    pos = np.searchsorted(t, hb_t).clip(0, n - 1)
    hb = pd.DataFrame({'vehicleId': row.vehicle_id, 'created': (hb_t + 3) * 1000, 'chargeOn': charge[pos],
                       'engineOn': ign[pos], 'voltPct': volt[pos], 'gsmPct': lc.gsmPct.mean()})[hk]
    return lc.reset_index(drop=True), hb.reset_index(drop=True)
