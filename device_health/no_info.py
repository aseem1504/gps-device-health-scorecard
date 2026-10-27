"""Blackouts ("no info"): find them, count them, size them.

Ported from:
  08_no_info_detection_module.ipynb   -> detect_no_info  (gap of more than 1 hour between pings)
  18_sim_network_airtel_vs_vodafone   -> no_info_summary (count, average and total hours per vehicle)
  21_no_info_quick_validation          -> gap_profile     (how many 10 / 30 / 60 / 180 min gaps a device has)

Fix: the original detection module had `elif (len(hb)==0)&(len(lc)==0)` for the
location-only branch, so it only ever ran when there were no pings at all. It should read
`len(lc) > 0`. Fixed here.
"""
import pandas as pd


def detect_no_info(lc, hb, threshold=3600):
    src = hb if hb is not None and len(hb) else lc
    if src is None or len(src) == 0:
        return pd.DataFrame(columns=['vehicleId', 'fromTime', 'toTime'])
    s = src.sort_values('created').copy()
    s['created'] = s['created'] / 1000
    s['created_shift'] = s['created'].shift(1)
    s['created_diff'] = s['created'] - s['created_shift']
    gaps = s[s['created_diff'] > threshold]
    return pd.DataFrame({'vehicleId': gaps['vehicleId'].values,
                         'fromTime': gaps['created_shift'].values, 'toTime': gaps['created'].values})


def no_info_summary(device_history):
    """device_history: vehicleId, fromTime, toTime for many vehicles."""
    d = device_history.copy()
    d['hours'] = (d['toTime'] - d['fromTime']) / 3600
    g = d.groupby('vehicleId')['hours']
    return pd.DataFrame({'number_of_times': g.size(), 'avg_time': g.mean(), 'total_noinfo': g.sum()}).reset_index()


def gap_profile(lc):
    c = (lc['created'] / 1000).sort_values()
    gap_min = c.diff() / 60
    return {f'gaps_over_{m}_min': int((gap_min > m).sum()) for m in (10, 30, 60, 180)}
