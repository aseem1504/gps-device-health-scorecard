"""Fire the device health Lambda for many vehicles, 100 at a time.

Port of notebooks/original/01_lambda_device_health_invoker.ipynb. The original posted
{"vehicle_id": [vid]} to an API Gateway URL from a thread pool of 100.

    DEVICE_HEALTH_LAMBDA_URL=https://<api-id>.execute-api.<region>.amazonaws.com/<stage>/vehicles \
    python aws_lambda/invoke.py vehicle_ids.csv
"""
import csv
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ.get('DEVICE_HEALTH_LAMBDA_URL', '')


def lambda_hit(batch):
    req = urllib.request.Request(URL, data=json.dumps({'vehicle_id': batch}).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=900) as r:
        print(f" - {r.status} -- vehicles: {batch[0]}..{batch[-1]} - ")
        return r.status


def main(path, batch_size=100, workers=10):
    if not URL:
        sys.exit("Set DEVICE_HEALTH_LAMBDA_URL first.")
    with open(path) as f:
        ids = [int(r[0]) for r in csv.reader(f) if r and r[0].isdigit()]
    batches = [ids[i:i + batch_size] for i in range(0, len(ids), batch_size)]
    with ThreadPoolExecutor(workers) as pool:
        print(list(pool.map(lambda_hit, batches)))


if __name__ == '__main__':
    main(sys.argv[1])
