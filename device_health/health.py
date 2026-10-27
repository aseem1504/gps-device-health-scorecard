"""One row of device health per vehicle per day.

Ported from the daily snapshot job (notebooks/original/02, 03, 04). The original had four
nearly identical 200-line functions; the maths is the same here, the shared parts are just
pulled into helpers. Column names, thresholds and the branch logic are unchanged:

    location pings + heartbeat  -> hb_lc
    location pings only         -> lc_only
    heartbeat only              -> hb_only
    nothing                     -> no_data   (every metric = -1)

Inputs are DataFrames instead of live API / Mongo calls:
    lc  location pings : vehicleId, time (s), created (ms), location [lon, lat], speed, usedSat, gsmPct
    hb  heartbeat pings: vehicleId, created (ms), chargeOn, engineOn, voltPct, gsmPct
    device_history     : blackout events for the day, columns fromTime, toTime (s)

Fixes vs the original:
  * hb_only read satellites from an undefined `df`; it now reads them from the heartbeat
  * chained filters df[a][b] replaced with df[a & b]
  * a day with zero driving or zero stop time no longer divides by zero
"""
import datetime as dt

import numpy as np
import pandas as pd

from .geo import haversine

COLUMNS = ['vehicle_id', 'day', 'total_raw_pings', 'heart_beat_pings',
           'usedSat_mean', 'usedSat_1_pctl', 'usedSat_5_pctl', 'usedSat_10_pctl', 'usedSat_50_pctl',
           'Gsm_mean', 'Gsm_1_pctl', 'Gsm_5_pctl', 'Gsm_10_pctl', 'Gsm_50_pctl',
           'cnsctv_time_diff_mean', 'cnsctv_time_diff_50_pctl', 'cnsctv_time_diff_80_pctl',
           'cnsctv_time_diff_95_pctl', 'cnsctv_time_diff_99_pctl',
           'server_delay_mean', 'server_delay_50_pctl', 'server_delay_80_pctl', 'server_delay_95_pctl',
           'server_delay_99_pctl',
           'jump_ping_500mts_count', 'jump_500mts_mean', 'jump_500mts_50_pctl', 'jump_500mts_80_pctl',
           'jump_500mts_95_pctl', 'jump_500mts_99_pctl',
           'driving_pings', 'stop_pings', 'driving_time', 'stop_time', 'total_distace_travelled',
           'live_time', 'offline_time',
           'created_3mins_ping_count', 'created_cnsctv_mean', 'created_cnsctv_50_pctl', 'created_cnsctv_80_pctl',
           'created_cnsctv_95_pctl', 'created_cnsctv_99_pctl',
           'jump_distance', 'jump_percent', 'expected_run_pings_percent', 'expected_stop_pings_percent',
           'no_info_distance_travelled', 'no_info_duration', 'no_info_instances']
# Added column (not in the original 50): jumps that are physically impossible, see README
EXTRA = ['gps_jump_percent']

getDay = lambda x: dt.datetime.fromtimestamp(x).date()


def _low(s):   # mean, 1%, 5%, 10%, 50%  (same as describe(...).values[[1,4,5,6,7]] in the original)
    s = pd.to_numeric(s, errors='coerce').dropna()
    if s.empty:
        return [np.nan] * 5
    return [s.mean()] + list(s.quantile([0.01, 0.05, 0.10, 0.50]).values)


def _high(s, with_count=False):   # (count,) mean, 50%, 80%, 95%, 99%
    s = pd.to_numeric(s, errors='coerce').dropna()
    vals = [np.nan] * 5 if s.empty else [s.mean()] + list(s.quantile([0.50, 0.80, 0.95, 0.99]).values)
    return ([len(s)] if with_count else []) + vals


def _no_info_epochs(df, device_history):
    """For each blackout, the last ping before it and the first ping after it."""
    epochs = []
    if device_history is None or device_history.empty:
        return epochs
    x = df.sort_values('time')
    for _, brow in device_history.sort_values('fromTime').iterrows():
        before = x[x['time'] < brow['fromTime']]
        after = x[x['time'] > brow['toTime']]
        start = before['time'].iloc[-1] if len(before) else 999999999999
        end = after['time'].iloc[0] if len(after) else 0
        epochs.append([start, end])
    return epochs


def _liveness(created, day_start, day_end):
    """Live = gaps under 3 min between server receipts; offline = the rest.
    created: server receipt times in seconds."""
    c = created.sort_values(ascending=False).reset_index(drop=True)
    gap = c.shift(1) - c
    gap.iloc[0] = 0
    live = gap[gap < 180].sum()
    offline = gap[gap > 180].sum()
    head, tail = c.min() - day_start, day_end - c.max()
    offline += (head if head >= 180 else 0) + (tail if tail >= 180 else 0)
    live += (head if head < 180 else 0) + (tail if tail < 180 else 0)
    no_info = gap[gap > 3600].sum() + (head if head >= 3600 else 0) + (tail if tail >= 3600 else 0)
    return live, offline, no_info, gap


def _location_metrics(df, device_history):
    df = df.sort_values('time', ascending=False).reset_index(drop=True)
    epochs = _no_info_epochs(df, device_history)
    sats = _low(df['usedSat']) if 'usedSat' in df else [-1] * 5
    gsm = _low(df['gsmPct']) if 'gsmPct' in df else [-1] * 5

    df['loc2'] = df['location'].shift(1)
    df['time1'] = df['time'].shift(1)
    df = df[1:].copy()
    df['time_diff_cons_pings'] = df['time1'] - df['time']
    df['server_created_time'] = df['created'] / 1000
    df['server_delay'] = df['server_created_time'] - df['time']
    a = np.radians(np.array(df['location'].tolist(), dtype=float))
    b = np.radians(np.array(df['loc2'].tolist(), dtype=float))
    # same haversine formula as geo.haversine, vectorised so a full day of pings is fast
    h = np.sin((b[:, 1] - a[:, 1]) / 2) ** 2 + np.cos(a[:, 1]) * np.cos(b[:, 1]) * np.sin((b[:, 0] - a[:, 0]) / 2) ** 2
    df['distance'] = 2 * 6371000 * np.arcsin(np.sqrt(h))

    no_info_distance = sum(df[(df['time'] >= s) & (df['time'] <= e)]['distance'].sum() for s, e in epochs)
    jumps = df[df['distance'] > 500]['distance']
    df['speed_self_cal'] = df['distance'] / df['time_diff_cons_pings']   # m/s
    # added: a >500 m hop only counts as a GPS error if the truck would have needed >150 km/h
    impossible = df[(df['distance'] > 500) & (df['speed_self_cal'] > 150 / 3.6)]['distance'].sum()
    running = df['speed_self_cal'] > 0.8
    total = df['distance'].sum()
    driving_time = df.loc[running, 'time_diff_cons_pings'].sum()
    stop_time = df.loc[~running, 'time_diff_cons_pings'].sum()
    return {
        'df': df, 'sats': sats, 'gsm': gsm,
        'gaps': _high(df['time_diff_cons_pings']), 'delay': _high(df['server_delay']),
        'jumps': _high(jumps, with_count=True),
        'driving_count': int(running.sum()), 'stop_count': int((~running).sum()),
        'driving_time': driving_time, 'stop_time': stop_time, 'total': total,
        'jump_distance': jumps.sum(), 'jump_percent': 100 * jumps.sum() / total if total else 0,
        'run_pct': 1000 * running.sum() / driving_time if driving_time else 0,
        'stop_pct': 3000 * (~running).sum() / stop_time if stop_time else 0,
        'no_info_distance': no_info_distance,
        'gps_jump_percent': 100 * impossible / total if total else 0,
        'day': getDay((df['time'].min() + df['time'].max()) / 2),
    }


def _row(vid, day, raw, hb_n, m, live, offline, created_gaps, no_info_duration, instances):
    gaps_over = created_gaps[created_gaps > 180]
    values = ([vid, day, raw, hb_n] + m['sats'] + m['gsm'] + m['gaps'] + m['delay'] + m['jumps'] +
              [m['driving_count'], m['stop_count'], m['driving_time'], m['stop_time'], m['total'], live, offline] +
              _high(gaps_over, with_count=True) +
              [m['jump_distance'], m['jump_percent'], m['run_pct'], m['stop_pct'], m['no_info_distance'],
               no_info_duration, instances, m.get('gps_jump_percent', -1)])
    return pd.DataFrame([values], columns=COLUMNS + EXTRA)


def lc_only(lc, l, device_history=None):
    vid, day_start, day_end = l
    try:
        m = _location_metrics(lc.copy(), device_history)
        live, offline, no_info, gaps = _liveness(m['df']['server_created_time'], day_start, day_end)
        n = 0 if device_history is None else len(device_history)
        return _row(vid, m['day'], len(lc), None, m, live, offline, gaps, no_info, n)
    except Exception as e:
        print(f"lc_only issue for {l}: {e}")
        return pd.DataFrame()


def hb_lc(hb, lc, l, device_history=None):
    """Location metrics from the location pings; live/offline time from the heartbeat."""
    vid, day_start, day_end = l
    try:
        m = _location_metrics(lc.copy(), device_history)
        live, offline, no_info, _ = _liveness(hb['created'] / 1000, day_start, day_end)
        _, _, _, gaps = _liveness(m['df']['server_created_time'], day_start, day_end)
        n = 0 if device_history is None else len(device_history)
        return _row(vid, m['day'], len(lc), len(hb), m, live, offline, gaps, no_info, n)
    except Exception as e:
        print(f"hb_lc issue for {l}: {e}")
        return pd.DataFrame()


def hb_only(hb, l, device_history=None):
    vid, day_start, day_end = l
    try:
        created = hb['created'] / 1000
        live, offline, no_info, gaps = _liveness(created, day_start, day_end)
        m = {'sats': _low(hb['usedSat']) if 'usedSat' in hb else [-1] * 5,
             'gsm': _low(hb['gsmPct']) if 'gsmPct' in hb else [-1] * 5,
             'gaps': [-1] * 5, 'delay': [-1] * 5, 'jumps': [-1] * 6,
             'driving_count': -1, 'stop_count': -1, 'driving_time': -1, 'stop_time': -1, 'total': -1,
             'jump_distance': -1, 'jump_percent': -1, 'run_pct': -1, 'stop_pct': -1, 'no_info_distance': None}
        n = 0 if device_history is None else len(device_history)
        return _row(vid, getDay((day_start + day_end) / 2), 0, len(hb), m, live, offline, gaps, no_info, n)
    except Exception as e:
        print(f"hb_only issue for {l}: {e}")
        return pd.DataFrame()


def no_data(l):
    vid, day_start, day_end = l
    return pd.DataFrame([[vid, getDay((day_start + day_end) / 2), 0, 0] + [-1] * 47], columns=COLUMNS + EXTRA)


def device_health_day(lc, hb, l, device_history=None):
    """Same branching as analysis_flow in the original."""
    lc = pd.DataFrame() if lc is None else lc
    hb = pd.DataFrame() if hb is None else hb
    if len(hb) > 5 and len(lc) > 5:
        return hb_lc(hb, lc, l, device_history)
    if len(lc) > 5:
        return lc_only(lc, l, device_history)
    if len(hb) > 5:
        return hb_only(hb, l, device_history)
    return no_data(l)
