import json
import os

import numpy as np
import pandas as pd

from device_health import actions, health, simulate
from device_health.no_info import detect_no_info
from device_health.sources import SimulatedPingSource

START = 1_600_041_600


def one_day(model='MODEL_A', network='NET_1', fault='none', seed=1):
    row = pd.Series({'vehicle_id': 1, 'model_name': model, 'network': network, 'installer': 'X', 'wiring_fault': fault})
    return simulate.vehicle_day(np.random.default_rng(seed), row, START)


def test_branches_and_columns():
    lc, hb = one_day('MODEL_A')            # has heartbeat
    l = [1, START, START + 86400]
    out = health.device_health_day(lc, hb, l, detect_no_info(lc, hb))
    assert list(out.columns) == health.COLUMNS + health.EXTRA and out.heart_beat_pings.iloc[0] > 0
    out = health.device_health_day(lc, None, l)
    assert pd.isna(out.heart_beat_pings.iloc[0])     # lc_only leaves heartbeat empty, like the original
    assert health.device_health_day(None, None, l).total_raw_pings.iloc[0] == 0


def test_speed_check_separates_bad_gps_from_gaps():
    l = [1, START, START + 86400]
    good = health.device_health_day(*one_day('MODEL_B', 'NET_2'), l)
    jumpy = health.device_health_day(*one_day('MODEL_C', 'NET_1'), l)
    assert jumpy.gps_jump_percent.iloc[0] > 3 * good.gps_jump_percent.iloc[0]


def test_action_rules():
    days = pd.date_range('2020-09-01', periods=6).date
    h = pd.DataFrame({'vehicle_id': 1, 'day': days, 'jump_percent': 30.0})
    w = pd.DataFrame({'vehicle_id': 1, 'day': days, **{k: False for k in actions.WIRE}})
    assert actions.action_analysis(1, h, w)['action_required'] == 'replace_device'
    w['wire_loose'] = True
    assert actions.action_analysis(1, h, w)['action_required'] == 'escalation_required'


def test_lambda_handler_locally():
    os.environ['PING_SOURCE'] = 'simulated'
    from aws_lambda.lambda_function import lambda_handler
    body = json.loads(lambda_handler({'vehicle_id': [500000]})['body'])
    assert body['processed'] == 1 and 0 <= body['vehicles'][0]['health_score'] <= 100
