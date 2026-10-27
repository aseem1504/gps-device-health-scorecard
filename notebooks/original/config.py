"""Connection settings for the original notebooks in this folder.

The notebooks were written against internal company databases and APIs. Every password,
host and URL has been removed. If you have your own equivalents, put them in a `.env`
file (see `.env.example` at the repo root) and these handles will be created.
Without them, the handles stay `None` and the notebooks serve as readable reference code.
The runnable version of the project lives outside this folder and needs none of this.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

env = os.environ.get

# REST services used by the notebooks
GPS_API_BASE = env("GPS_API_BASE", "http://localhost:8080")          # location + heartbeat pings
DEVICE_API_BASE = env("DEVICE_API_BASE", "http://localhost:8081")    # device / SIM service
FASTAG_API_BASE = env("FASTAG_API_BASE", "http://localhost:8082")    # FASTag service
DOC_STORE_API_BASE = env("DOC_STORE_API_BASE", "http://localhost:8083")  # KYC document store
VISION_API_BASE = env("VISION_API_BASE", "http://localhost:8084")    # OCR wrapper service
GOOGLE_SHEET_URL = env("GOOGLE_SHEET_URL", "")


def _sql(url_var):
    url = env(url_var)
    if not url:
        return None
    from sqlalchemy import create_engine
    return create_engine(url)


def _mongo(url_var):
    url = env(url_var)
    if not url:
        return None
    from pymongo import MongoClient
    return MongoClient(url)


# SQL: analytics Postgres, data lake (Redshift), production read replicas (MySQL)
engine = postgres = _sql("ANALYTICS_DB_URL")
con = datalake = _sql("DATALAKE_DB_URL")
mysql_cn = mysql_vds = _sql("FLEET_DB_URL")
mysql_users = _sql("USERS_DB_URL")

# Mongo: telematics store and the analytics scratch store
client = client2 = _mongo("TELEMATICS_MONGO_URI")
client_db = _mongo("ANALYTICS_MONGO_URI")
app_mongo = _mongo("APP_MONGO_URI")
