"""Rule engine that flags wiring faults and tampering from one vehicle-day of pings.

Ported from notebooks/original/01_wire_issues_module.ipynb (Sept 2020 version).
Logic and thresholds are unchanged. Changes made for this public version:
  * pings are passed in as DataFrames instead of being pulled from the internal GPS API
  * boolean columns are cast to int before subtracting (newer pandas refuses bool - bool)
  * chained boolean indexing df[a][b] replaced with df[a & b] (same result, no warnings)

Ping formats
------------
location pings (lc): vehicleId, time (epoch s), created (epoch s), location [lon, lat], speed,
                     and for devices without a heartbeat channel: chargeOn, ignOn, voltPct
heartbeat pings (hb): vehicleId, created (epoch ms), updated, chargeOn, engineOn, voltPct
"""
import datetime as dt

import numpy as np
import pandas as pd

from .geo import haversine

COLUMNS = ['day', 'vehicle_id', 'intentional_wire_cut', 'maintainence_wire_cut', 'wire_loose',
           'charge_to_ign', 'ign_wire_cut', 'ign_to_charge']

getDay = lambda x: dt.datetime.fromtimestamp(x).date()


def _add_motion(df):
    loc_list = df[['location', 'loc2']].values.tolist()
    df.loc[:, 'distance'] = [haversine(a, b) for a, b in loc_list]
    df.loc[:, 'speed_self_cal'] = df['distance'] / df['time_diff_cons_pings'] * 3.6  # km/h
    df.loc[:, 'moving_status'] = np.where(df['speed_self_cal'] > 5, 'running', 'stop')
    return df


def hb_lc_wire_issue(hbc, dfc):
    """Devices that send location pings AND a separate heartbeat (charge / engine / voltage)."""
    hb = hbc.copy()
    df = dfc.copy()
    vehicle_id = None
    try:
        hb.sort_values('created', inplace=True)
        hb.created = (hb.created / 1000).astype(int)
        del df['created']
        del df['vehicleId']
        if 'updated' in hb:
            del hb['updated']
        df.sort_values('time', inplace=True)

        if len(hb) < len(df):
            df = pd.merge_asof(left=df, right=hb, left_on='time', right_on='created', direction='nearest')
        else:
            df = pd.merge_asof(left=hb, right=df, left_on='created', right_on='time', direction='nearest')
        df.loc[:, 'loc2'] = df['location'].shift(1)
        df.loc[:, 'time1'] = df['time'].shift(-1)
        df = df[1:].copy()
        df.loc[:, 'time_diff_cons_pings'] = df['time1'] - df['time']
        df = _add_motion(df)

        day = getDay((df['time'].min() + df['time'].max()) / 2)
        charge = df['chargeOn'].astype(int)
        engine = df['engineOn'].astype(int)

        #### WIRE CUT PARAMETERS ####
        off = df['chargeOn'] == False
        charge_off_Speed = df.loc[off, 'speed_self_cal'].min()
        wire_cut_time = df.loc[off, 'time_diff_cons_pings'].sum()
        min_voltage_pct_when_wire_cut = df.loc[off, 'voltPct'].min()

        #### LOOSE WIRE ####
        fluctuations = np.nansum(abs(charge - charge.shift(1)))

        #### CHARGE CONNECTED TO IGN ####
        charge_to_ign = bool((charge == engine).all()) & (fluctuations > 2)

        #### IGN WIRE CUT ####
        ign_wire_cut = (len(df[(df['engineOn'] == False) & (df['speed_self_cal'] > 10)]) > 20) & \
                       (len(df[df['engineOn'] == True]) < 1)

        #### IGN WIRE TO CHARGE ####
        ign_to_charge = len(df[(df['chargeOn'] == True) & (df['engineOn'] == False)]) == 0

        intentional_wire_cut = (charge_off_Speed > 10 / 3.6) & (wire_cut_time > 3600) & (min_voltage_pct_when_wire_cut < 60)
        maintainence_wire_cut = (charge_off_Speed < 2 / 3.6) & (wire_cut_time > 3600) & (min_voltage_pct_when_wire_cut < 60)
        wire_loose = fluctuations > 2
        vehicle_id = df.vehicleId.iloc[0]
        values = [day, vehicle_id, intentional_wire_cut, maintainence_wire_cut, wire_loose,
                  charge_to_ign, ign_wire_cut, ign_to_charge]
        return pd.DataFrame([values], columns=COLUMNS)
    except Exception as e:
        print("The issue with the wire_issue_hb_lc {} is--- ".format(vehicle_id) + str(e))
        return None


def lc_only_wire_issue(dfc):
    """Devices where charge / ignition / voltage ride along with each location ping."""
    df = dfc.copy()
    vehicle_id = None
    try:
        df.sort_values('time', ascending=False, inplace=True)
        df.loc[:, 'loc2'] = df['location'].shift(1)
        df.loc[:, 'time1'] = df['time'].shift(1)
        df = df[1:].copy()
        df.loc[:, 'time_diff_cons_pings'] = df['time1'] - df['time']
        df = _add_motion(df)

        day = getDay((df['time'].min() + df['time'].max()) / 2)
        charge = df['chargeOn'].astype(int)
        ign = df['ignOn'].astype(int)

        #### WIRE CUT PARAMETERS ####
        off = df['chargeOn'] == False
        charge_off_Speed = df.loc[off, 'speed_self_cal'].min()
        wire_cut_time = df.loc[off, 'time_diff_cons_pings'].sum()
        min_voltage_pct_when_wire_cut = df.loc[off, 'voltPct'].min()

        #### LOOSE WIRE ####
        fluctuations = np.nansum(abs(charge - charge.shift(1)))

        #### CHARGE CONNECTED TO IGN ####
        charge_to_ign = bool((charge == ign).all()) & (fluctuations > 2)

        #### IGN WIRE CUT ####
        ign_wire_cut = (len(df[(df['ignOn'] == False) & (df['speed_self_cal'] > 10)]) > 20) & \
                       (len(df[df['ignOn'] == True]) < 1)

        #### IGN WIRE TO CHARGE ####
        ign_to_charge = (len(df[(df['chargeOn'] == True) & (df['ignOn'] == False)]) == 0) & (fluctuations < 3)

        intentional_wire_cut = (charge_off_Speed > 12 / 3.6) & (wire_cut_time > 3600) & (min_voltage_pct_when_wire_cut < 60)
        maintainence_wire_cut = (charge_off_Speed < 2 / 3.6) & (wire_cut_time > 3600) & (min_voltage_pct_when_wire_cut < 60)
        wire_loose = fluctuations > 2
        vehicle_id = df.vehicleId.iloc[0]
        values = [day, vehicle_id, intentional_wire_cut, maintainence_wire_cut, wire_loose,
                  charge_to_ign, ign_wire_cut, ign_to_charge]
        return pd.DataFrame([values], columns=COLUMNS)
    except Exception as e:
        print("The issue with the function lc_only_wire_issue for vehicle_id {} is --- ".format(vehicle_id) + str(e))
        return None


def analysis_flow(lc, hb=None):
    """Pick the right rule set based on which ping streams exist (same branching as the original)."""
    hb = pd.DataFrame() if hb is None else hb
    if (len(hb) > 5) & (len(lc) > 5):
        return hb_lc_wire_issue(hb, lc)
    elif (len(lc) > 5) & (len(hb) < 1):
        return lc_only_wire_issue(lc)
    print("analysis_flow: not enough heartbeat and location pings")
    return None
