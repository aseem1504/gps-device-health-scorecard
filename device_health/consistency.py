"""Two simple uptime metrics that the ops team could read at a glance.

Ported from notebooks/original/07_data_consistency_pings_per_min.ipynb.

  1_min_data            hours in the day with at least one ping in that minute (out of 24)
  15_min_live_tracking  hours where pings kept arriving with gaps under 5 min
                        (15 min for devices that also send a heartbeat)
"""
import pandas as pd


def ping_analysis(lc, hb, l):
    vid, start, end = l
    lc = pd.DataFrame() if lc is None else lc
    hb = pd.DataFrame() if hb is None else hb
    day = pd.Timestamp((start + end) / 2, unit='s').date()

    def minutes_with_data(times):
        t = pd.to_datetime(pd.Series(times), unit='s')
        counts = pd.Series(1, index=t).resample('min').count()
        filled = (counts > 0).sum()
        return filled / 60

    if len(hb) == 0 and len(lc) > 0:
        hours = minutes_with_data(lc['time'])
        c = (lc['created'] / 1000).sort_values()
        gap = c.diff()
        live = gap[gap < 5 * 60].sum() / 3600
        status = 'No heartbeat'
    elif len(hb) > 0:
        times = pd.concat([hb['created'] / 1000, lc['time']]) if len(lc) else hb['created'] / 1000
        hours = minutes_with_data(times)
        c = (hb['created'] / 1000).sort_values()
        gap = c.diff()
        live = gap[gap < 15 * 60].sum() / 3600
        status = 'Has heartbeat'
    else:
        hours, live, status = 0, 0, 'No data'
    return {'vehicle_id': vid, '1_min_data': round(hours, 2), '15_min_live_tracking': round(live, 2),
            'data_status': status, 'day': day}
