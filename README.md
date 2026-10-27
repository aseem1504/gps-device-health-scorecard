# GPS Device Health Scorecard

A daily health check for every GPS tracker in a truck fleet. It runs as an AWS Lambda, writes one row per device per day, rolls those rows up by device model, SIM network and installer, and tells ops what to do with each truck: replace the device, send an installer, or leave it alone.

Built in 2019 to 2021 for a truck GPS fleet. All data in this repo is synthetic.

Sister repo: [truck-gps-tamper-detector](https://github.com/aseem1504/truck-gps-tamper-detector) uses the same ping data to catch wiring faults and tampering.

## The problem

A GPS business lives or dies on one promise: the dot on the map is right, and it is live. Every tracker that goes quiet becomes a support call, and often a lost customer.

Trackers fail for very different reasons. Some hardware models have weak GPS chips that throw the truck kilometres off the road. Some store data and upload it late, so the "live" map is minutes behind. Some SIM networks drop out in parts of the country. Some installers wire devices badly, or mostly fit SIMs from the weaker network. Each of these needs a different fix from a different team. Without a daily, per-device view, they all look the same: "GPS not working".

## How it works

**1. The daily job (AWS Lambda).** `aws_lambda/lambda_function.py` takes a batch of vehicle ids, like the original API Gateway call `{"vehicle_id": [...]}`. For each vehicle it finds the last ping, looks back 24 hours, and pulls the location pings and the heartbeat pings. Then it picks one of four paths, as the original did: location plus heartbeat, location only, heartbeat only, or no data. `aws_lambda/invoke.py` fires the Lambda for the whole fleet in batches of 100. `aws_lambda/template.yaml` is a deployable SAM template with a nightly schedule.

**2. One health row per device per day.** Fifty columns, the same ones the production table had. They cover:

- how many pings arrived, and the gaps between them
- satellites used and GSM signal strength
- server delay (how late each ping reached the server)
- GPS jumps over 500 m
- driving and stopped time, live and offline time
- blackouts, and the distance covered while dark

Two simpler uptime numbers sit on top. The first is hours in the day with at least one ping each minute. The second is hours of live tracking.

**3. A scorecard.** Rows roll up by device model, SIM network and installer. That answers the vendor question (which hardware is failing), the network question (which SIM partner), and the field question (which installer).

**4. Actions.** Two rules from the original turn history into decisions:

- **Blacklist:** if GPS jumps are more than 20% of a device's distance, averaged over more than 3 days, the device is bad hardware. Swap it.
- **Action rule:** over the last 9 days, few wiring flags but jumpy GPS means replace the device. Repeated wiring flags mean escalate and send an installer. Anything else means the device is working fine.

**5. A single health score (added).** The original table had 50 columns and no number a manager could sort by. The score is a weighted mix of things the team already tracked:

health score = 40% x live time share + 25% x (100 - jump percent) + 20% x data coverage + 15% x (100 - share of the day lost to blackouts)

`score = 0.40*live + 0.25*(100 - jump) + 0.20*coverage + 0.15*(100 - blackout)`

The weights are a starting point. They say "being online matters most". They are not a finding.

## Results on synthetic data

`python demo.py` runs the Lambda logic for 100 trucks over 6 days. The fake fleet has five fictional device models, each with a planted flaw. `MODEL_C` has a jumpy GPS chip, `MODEL_D` uploads late, and `MODEL_E` drops a quarter of its pings. There are also two SIM networks (`NET_2` drops out more often), 12 installers, and a few wiring faults.

| Model | Avg health score | Live hours / day | Jump % (original) | Jump % (speed-checked) | Median server delay |
|---|---|---|---|---|---|
| MODEL_E | 72 | 11.7 | 13 | 1.8 | 13 s |
| MODEL_C | 80 | 20.7 | 40 | 30.6 | 17 s |
| MODEL_D | 84 | 19.6 | 16 | 2.1 | 167 s |
| MODEL_B | 87 | 20.9 | 16 | 3.6 | 14 s |
| MODEL_A | 87 | 20.4 | 13 | 2.4 | 10 s |

On networks, `NET_2` trucks had 3 times as many blackouts as `NET_1` trucks (12.8 vs 3.9 per vehicle over 6 days). The three installers who fit mostly `NET_2` SIMs show up by name.

## What the numbers say

**The jump metric was measuring two different things.** The original counts any hop over 500 m between two pings as a "jump". But when a truck loses network for an hour and then reconnects 40 km down the highway, that is also a hop over 500 m. So the metric mixed bad GPS with bad network. Every model scored 13 to 16%, and the truly jumpy one only stood out at 40%.

That mattered because both action rules ran on it:

| | Original jump metric | Speed-checked jump metric (added) |
|---|---|---|
| Blacklisted devices | 36 (all 14 jumpy, plus 22 healthy) | 14 (all 14 jumpy, no others) |
| Healthy trucks told "replace device" | 70 of 72 | 3 of 72 |

The fix is one line of logic. Only count a hop as a GPS error if the truck would have needed more than 150 km/h to make it. On a real fleet, a false "replace device" is a technician visit plus a new tracker. Getting this metric wrong is a cost line, not a rounding error.

**A single score hides what a customer feels.** `MODEL_D` scores 84, close to the best. But its pings reach the server almost 3 minutes late. A fleet owner watching the live map would call it broken. The score treats a late ping the same as an on-time one, because the original metrics did too. Before a score like this goes on a dashboard, someone has to decide what "healthy" means to the customer. Then the weights should follow that decision.

**Network beats hardware more often than people expect.** Health scores split as much by SIM network (76 vs 89) as by device model. The installer table explains part of it: a few installers fit most of the weak network's SIMs. This is the kind of root cause a per-device view finds and a per-ticket view never does.

## Run it

```bash
pip install -r requirements.txt
python demo.py                                       # full synthetic run, about a minute
PING_SOURCE=simulated python aws_lambda/lambda_function.py   # call the Lambda handler locally
pytest
```

To deploy the Lambda (needs the AWS SAM CLI and your own telematics API):

```bash
sam build -t aws_lambda/template.yaml
sam deploy --guided        # asks for GpsApiBase and, optionally, HealthDbUrl
```

## Repo layout

```
aws_lambda/
  lambda_function.py   the Lambda handler (daily job), port of the original snapshot Lambda
  invoke.py            fires the Lambda for many vehicles, 100 at a time
  template.yaml        SAM template: function, API endpoint, nightly schedule
device_health/
  health.py            the 50-column daily health row (hb_lc / lc_only / hb_only / no_data)
  consistency.py       hours with data, hours of live tracking
  no_info.py           blackout detection and per-vehicle blackout summary
  actions.py           blacklist rule and replace / escalate / fine rule
  scorecard.py         rollups by model, network, installer; health score
  wire_issues.py       wiring-fault rules (shared with the tamper repo)
  sources.py           HTTP ping source (real API) and simulated source
  simulate.py          synthetic fleet with planted device, network and wiring problems
demo.py                end-to-end run
data/sample/           small samples of the synthetic pings
notebooks/original/    22 original notebooks, cleaned (see the README inside)
```

## What changed from the original code

The metrics, thresholds and branch logic are the original ones. The changes:

- Pings come from a pluggable source instead of hard-wired internal API and Mongo calls.
- Four near-identical 200-line functions became four short ones sharing helpers. The maths is the same.
- `hb_only` read satellite counts from an undefined variable. Fixed.
- The blackout detector's location-only branch could never run (`len(lc)==0` where it meant `> 0`). Fixed.
- Percentiles are computed directly. Newer pandas no longer adds the median to `describe()` by itself, which broke the original column order.
- Distances are computed in one vectorised step instead of a Python loop. Same formula, much faster.
- Added: the speed-checked jump metric, the health score, the SAM template, and tests.

## Data and privacy

Device models, networks, installers, trucks and pings are all fictional and generated by `simulate.py`. The original notebooks had every output removed. Credentials, internal hosts and IPs, the API Gateway URL, the AWS account id, phone numbers, staff names and vehicle ids were also removed or replaced before upload.
