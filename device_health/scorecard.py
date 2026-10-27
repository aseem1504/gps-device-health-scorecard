"""Roll vehicle-days up into a fleet scorecard: by device model, by SIM network, by installer.

Ported from 06_device_health_analysis, 07_data_consistency (share of devices under 12 hours of
data, by model), 11_device_model_ranking and 18_sim_network_airtel_vs_vodafone.

`health_score` is new. The original tables had 50 columns per vehicle-day and no single
number a manager could sort by. The score is a plain weighted mix of four things the team
already tracked, each scaled 0-100:

    health score = 40% x live time share
                 + 25% x (100 - jump percent)
                 + 20% x data coverage (hours with a ping each minute / 24)
                 + 15% x (100 - share of the day lost to blackouts)

    score = 0.40*live + 0.25*(100 - jump) + 0.20*coverage + 0.15*(100 - blackout)

The weights are a starting point, not a finding. They say "being online matters most".
"""
import numpy as np
import pandas as pd


def health_score(row):
    if row['total_raw_pings'] <= 0 and (row['heart_beat_pings'] or 0) <= 0:
        return 0.0
    live = 100 * row['live_time'] / 86400
    jump = 0 if row['jump_percent'] < 0 else min(row['jump_percent'], 100)
    coverage = 100 * row.get('1_min_data', 0) / 24
    blackout = 100 * min(row['no_info_duration'], 86400) / 86400
    return round(float(np.clip(0.40 * live + 0.25 * (100 - jump) + 0.20 * coverage + 0.15 * (100 - blackout), 0, 100)), 1)


def by_group(daily, key):
    g = daily.groupby(key)
    return pd.DataFrame({
        'vehicles': g.vehicle_id.nunique(),
        'avg_health_score': g.health_score.mean().round(1),
        'live_hours': (g.live_time.mean() / 3600).round(1),
        'jump_percent': g.jump_percent.mean().round(1),
        'gps_jump_percent': g.gps_jump_percent.mean().round(1),
        'server_delay_s': g.server_delay_50_pctl.mean().round(0),
        'blackouts_per_day': g.no_info_instances.mean().round(2),
        'share_under_12h_data': g['1_min_data'].apply(lambda s: round(100 * (s < 12).mean(), 1)),
        'stoppage_ping_rate': g.expected_stop_pings_percent.mean().round(2),
    }).sort_values('avg_health_score').reset_index()


def network_comparison(no_info_summary, vehicles):
    d = no_info_summary.merge(vehicles, left_on='vehicleId', right_on='vehicle_id')
    g = d.groupby('network')
    return pd.DataFrame({'vehicles': g.vehicle_id.nunique(), 'blackouts_per_vehicle': g.number_of_times.mean().round(2),
                         'avg_blackout_hours': g.avg_time.mean().round(2),
                         'total_blackout_hours': g.total_noinfo.mean().round(1)}).reset_index()


def installer_network_mix(vehicles, weak_network, share=50):
    """From 18_...: installers whose SIM mix leans heavily on the weaker network."""
    t = pd.crosstab(vehicles.installer, vehicles.network)
    t['weak_network_percent'] = (100 * t.get(weak_network, 0) / t.sum(axis=1)).round(1)
    return t[t['weak_network_percent'] > share].sort_values('weak_network_percent', ascending=False)
