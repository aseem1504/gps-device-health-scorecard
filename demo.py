"""End-to-end demo on a synthetic fleet: python demo.py

1. run the daily Lambda job for every vehicle, every day, exactly as production did
2. roll the rows up into a scorecard by device model, SIM network and installer
3. turn health history into actions: replace the device, send an installer, or leave it
"""
import json
import os

import pandas as pd

from aws_lambda.lambda_function import analyse_vehicle, lambda_handler
from device_health import actions, scorecard
from device_health.no_info import detect_no_info, no_info_summary
from device_health.sources import SimulatedPingSource

pd.set_option('display.width', 220)
pd.set_option('display.max_columns', 20)
os.makedirs('outputs', exist_ok=True)

src = SimulatedPingSource(n_vehicles=100, days=6)
fleet = src.fleet
print(f"=== 1. Daily job: {len(fleet)} vehicles x {src.days} days ===")
health, wires, blackouts = [], [], []
for d in range(src.days):
    start = src.start_day + d * 86400
    for vid in fleet.vehicle_id:
        h, w = analyse_vehicle(vid, src, window=[vid, start, start + 86400])
        if len(h):
            health.append(h)
        if w is not None:
            wires.append(w)
        lc, hb = src.pings(vid, start, start + 86400)
        blackouts.append(detect_no_info(lc, hb))
health = pd.concat(health, ignore_index=True).merge(fleet, on='vehicle_id')
wires = pd.concat(wires, ignore_index=True)
blackouts = pd.concat(blackouts, ignore_index=True)
health.to_csv('outputs/device_health_daily.csv', index=False)
wires.to_csv('outputs/wire_issues_daily.csv', index=False)
print(f"{len(health)} vehicle-days scored, median health score {health.health_score.median():.0f}/100")

print("\n=== 2. Scorecard by device model (worst first) ===")
by_model = scorecard.by_group(health, 'model_name')
print(by_model.to_string(index=False))
print("\nBy SIM network:")
print(scorecard.by_group(health, 'network')[['network', 'vehicles', 'avg_health_score', 'live_hours', 'blackouts_per_day']].to_string(index=False))
print("\nBlackouts by network (from the no-info log):")
print(scorecard.network_comparison(no_info_summary(blackouts), fleet).to_string(index=False))
print("\nInstallers fitting mostly NET_2 SIMs:")
print(scorecard.installer_network_mix(fleet, 'NET_2').to_string())

print("\n=== 3. Actions ===")
models = fleet.set_index('vehicle_id').model_name
for col, label in [('jump_percent', 'original jump metric'), ('gps_jump_percent', 'speed-checked jump metric (added)')]:
    bl = actions.blacklist(health, column=col)
    hit = models.loc[bl[bl.blacklist].vehicle_id]
    print(f"blacklist with {label}: {len(hit)} devices | MODEL_C caught {int((hit == 'MODEL_C').sum())}/{int((models == 'MODEL_C').sum())}"
          f" | other models flagged {int((hit != 'MODEL_C').sum())}")
for col, label in [('jump_percent', 'original jump metric'), ('gps_jump_percent', 'speed-checked jump metric')]:
    rec = [actions.action_analysis(v, health, wires, jump_column=col) for v in fleet.vehicle_id]
    rec = pd.DataFrame([r for r in rec if r]).merge(fleet[['vehicle_id', 'model_name', 'wiring_fault']], on='vehicle_id')
    rec['truth'] = rec.apply(lambda r: 'wiring fault' if r.wiring_fault != 'none' else
                             ('jumpy device' if r.model_name == 'MODEL_C' else 'healthy'), axis=1)
    print(f"\nRecommended action vs the planted truth, using the {label}:")
    print(pd.crosstab(rec.truth, rec.action_required).to_string())
rec.to_csv('outputs/device_actions.csv', index=False)
by_model.to_csv('outputs/scorecard_by_model.csv', index=False)

print("\n=== 4. Lambda handler, called the way API Gateway would ===")
os.environ['PING_SOURCE'] = 'simulated'
out = lambda_handler({'body': json.dumps({'vehicle_id': [500000, 500001]})})
print(json.dumps(json.loads(out['body']), indent=1)[:900])
