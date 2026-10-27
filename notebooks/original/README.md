# Original notebooks

These are the notebooks as they were originally written and run, cleaned for public release.

What was removed or changed:

- Every cell output. Outputs held real query results, so none of them are here.
- Database and Mongo connection lines with hosts, users and passwords. They are replaced by
  `from config import *`, which reads settings from environment variables (see `../.env.example`).
- Internal hostnames, IP addresses, S3 bucket names, Google Sheet links, email addresses and
  local file paths. They are replaced by placeholders such as `GPS_API_BASE` or `data/`.
- Real vehicle IDs, replaced by sample IDs.

What was kept: the logic, the SQL, the comments, the half-finished experiments and the odd
Hinglish print statement. They show how the work actually happened.

These notebooks will not run without the company systems behind them. To see the ideas run end
to end, use `python demo.py` in the repo root, which uses synthetic data.
