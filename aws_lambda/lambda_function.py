"""AWS Lambda entry point for the daily device health job.

This is the base the original ran on. In 2020 the snapshot notebook was turned into a
Lambda (`lambda_handler(event, context)`) behind an API Gateway endpoint, and a small script
(notebooks/original/01_lambda_device_health_invoker.ipynb, ported as invoke.py) fired it for
batches of 100 live vehicles at a time.

Flow, same as the original:
  1. event carries vehicle ids:  {"vehicle_id": [101, 102, ...]}  (or a bare list)
  2. for each vehicle, find its last ping and look back 24 hours from there
  3. pull location + heartbeat pings, detect blackouts, compute the health row and wiring flags
  4. write to the `device_health` and `wire_issues` tables if HEALTH_DB_URL is set,
     and always return a JSON summary

Environment:
  PING_SOURCE    http (default) or simulated
  GPS_API_BASE   base URL of the telematics API, for PING_SOURCE=http
  HEALTH_DB_URL  optional SQLAlchemy URL for the output tables
  MAX_WORKERS    threads per invocation (default 10)
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))  # local runs: repo root on path

from device_health.consistency import ping_analysis
from device_health.health import device_health_day
from device_health.no_info import detect_no_info
from device_health.scorecard import health_score
from device_health.sources import HttpPingSource, SimulatedPingSource
from device_health.wire_issues import analysis_flow as wire_flow

_SOURCE = None


def get_source():
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = SimulatedPingSource() if os.environ.get('PING_SOURCE') == 'simulated' else HttpPingSource()
    return _SOURCE


def analyse_vehicle(vid, source=None, window=None):
    source = source or get_source()
    if window is None:
        last = source.last_ping(vid)
        window = [vid, last - 86400, last + 100] if last > 0 else [vid, 0, 200]
    l = [vid, int(window[1]), int(window[2])]
    lc, hb = source.pings(*l)
    blackouts = detect_no_info(lc, hb)
    health = device_health_day(lc, hb, l, blackouts)
    if len(health):
        health = health.assign(**ping_analysis(lc, hb, l))
        health['health_score'] = health.apply(health_score, axis=1)
    wire = wire_flow(lc, hb) if len(lc) > 5 else None
    return health, wire


def _write(health, wire):
    url = os.environ.get('HEALTH_DB_URL')
    if not url:
        return False
    from sqlalchemy import create_engine
    engine = create_engine(url)
    health.to_sql('device_health', con=engine, if_exists='append', index=False, chunksize=200)
    if wire is not None and len(wire):
        wire.to_sql('wire_issues', con=engine, if_exists='append', index=False, chunksize=200)
    return True


def lambda_handler(event, context=None):
    if isinstance(event, str):
        event = json.loads(event)
    if isinstance(event, dict) and 'body' in event:   # API Gateway proxy event
        event = json.loads(event['body'] or '{}')
    vehicles = event.get('vehicle_id', []) if isinstance(event, dict) else list(event)

    with ThreadPoolExecutor(int(os.environ.get('MAX_WORKERS', 10))) as pool:
        results = list(pool.map(analyse_vehicle, vehicles))

    health = pd.concat([h for h, _ in results if h is not None and len(h)], ignore_index=True) if results else pd.DataFrame()
    wire = [w for _, w in results if w is not None]
    wire = pd.concat(wire, ignore_index=True) if wire else pd.DataFrame()
    stored = _write(health, wire) if len(health) else False

    summary = []
    for _, r in health.iterrows():
        flags = []
        if len(wire):
            w = wire[wire.vehicle_id == r.vehicle_id]
            if len(w):
                flags = [c for c in w.columns[2:] if bool(w.iloc[0][c])]
        summary.append({'vehicle_id': int(r.vehicle_id), 'day': str(r.day), 'health_score': r.health_score,
                        'live_hours': round(r.live_time / 3600, 1), 'jump_percent': round(float(r.jump_percent), 1),
                        'gps_jump_percent': round(float(r.gps_jump_percent), 1),
                        'blackouts': int(r.no_info_instances), 'wire_flags': flags})
    return {'statusCode': 200, 'body': json.dumps({'processed': len(vehicles), 'stored': stored, 'vehicles': summary})}


if __name__ == '__main__':   # local test: PING_SOURCE=simulated python aws_lambda/lambda_function.py
    os.environ.setdefault('PING_SOURCE', 'simulated')
    print(json.dumps(json.loads(lambda_handler({'vehicle_id': [500000, 500001, 500002]})['body']), indent=2))
