"""Turn health history into a decision per vehicle.

Ported from:
  14_blacklist_jumpy_devices.ipynb       -> blacklist
  15_device_action_recommendation.ipynb  -> action_analysis

blacklist: a device whose GPS jumps make up more than 20% of its distance, averaged over
more than 3 days of data, is a bad device. It should be swapped, not debugged.

action_analysis: look at the last 9 days of health + wiring flags (needs at least 5 days):
  * few wiring flags but jumpy GPS             -> replace_device
  * repeated wiring flags                      -> escalation_required  (send an installer)
  * otherwise                                  -> device_working_fine
Thresholds are the original ones.
"""
import pandas as pd

WIRE = ['intentional_wire_cut', 'maintainence_wire_cut', 'wire_loose', 'charge_to_ign', 'ign_wire_cut', 'ign_to_charge']


def blacklist(device_health, min_days=3, jump_threshold=20, column='jump_percent'):
    """column='gps_jump_percent' uses the speed-checked jump metric added in this repo."""
    d = device_health.drop_duplicates(['day', 'vehicle_id'])
    d = d[d[column] != -1]
    g = d.groupby('vehicle_id')[column]
    out = pd.DataFrame({'jump_percent': g.mean(), 'number_of_days': g.size()}).reset_index()
    out['blacklist'] = (out['number_of_days'] > min_days) & (out['jump_percent'] > jump_threshold)
    return out


def action_analysis(vid, device_health, wire_issues, threshold=4, days=9, jump_column='jump_percent'):
    h = device_health[device_health.vehicle_id == vid].sort_values('day', ascending=False).head(days)
    w = wire_issues[wire_issues.vehicle_id == vid].sort_values('day', ascending=False).head(days)
    h = h.drop_duplicates(['vehicle_id', 'day'])
    w = w.drop_duplicates(['vehicle_id', 'day'])
    c = pd.merge(w, h, how='inner', on=['day', 'vehicle_id'])
    if len(c) <= threshold:
        return None
    n = {f'{k}_count': int(c[k].astype(bool).sum()) for k in WIRE}
    jump = c[jump_column].mean()
    if (n['wire_loose_count'] < 2) & (n['intentional_wire_cut_count'] < 2) & (n['charge_to_ign_count'] < 5) \
            & (jump > 5) & (n['ign_wire_cut_count'] < 2):
        action = 'replace_device'
    elif (n['wire_loose_count'] > 2) | (n['intentional_wire_cut_count'] > 2) | (n['charge_to_ign_count'] > 2) \
            | (n['maintainence_wire_cut_count'] > 2) | (n['ign_wire_cut_count'] > 2):
        action = 'escalation_required'
    else:
        action = 'device_working_fine'
    return {'vehicle_id': vid, 'action_required': action, 'jump_percent_avg': round(jump, 2),
            'days_seen': len(c), **n}
