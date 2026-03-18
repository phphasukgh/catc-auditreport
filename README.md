# catc-auditreport

A command-line tool to retrieve, paginate, and export Audit Log records from **Cisco Catalyst Center (CATC)** via its REST API.

---

## Features

- Retrieve audit logs using flexible filter options (category, severity, user, domain, device, site, etc.)
- **Relative period** shorthand (`30d`, `24h`, `90m`) that auto-calculates epoch start/end times
- **Auto-pagination** — iterates through all pages automatically when a time range is provided
- **Real-time progress** indicator that updates in place on a single terminal line
- Export to **CSV**, **JSON**, or **both** formats
- Epoch millisecond timestamps (`timestamp`, `startTime`, `endTime`) automatically converted to readable UTC datetime strings
- Nested fields (dicts/lists) serialised as JSON strings in CSV output
- Structured logging to a rotating log file (`logs/application_run.log`)
- Graceful handling of non-JSON and empty API responses with full diagnostic logging

---

## Requirements

- Python 3.10+
- `requests` library

Install dependencies:

```bash
pip install requests
```

---

## Configuration

Edit `catc_config.py` to set your Catalyst Center address:

```python
CATC_IP = '10.x.x.x'
CATC_PORT = 443
```

---

## Usage

```
python catc_auditreport.py [options]
```

The script prompts for **Username** and **Password** at runtime. Credentials are never stored.

### Time Range Options (mutually exclusive)

| Option | Description |
|---|---|
| `--period PERIOD` | Relative window ending now. Format: `<number><unit>` where unit is `d` (days), `h` (hours), `m` (minutes). Examples: `30d`, `24h`, `90m`. Auto-paginates. |
| `--start-time MS` `--end-time MS` | Absolute epoch-millisecond timestamps. Both must be supplied together. Auto-paginates. |
| *(none)* | Single API call using `--offset` and `--limit` as-is. |

### Pagination

| Option | Default | Description |
|---|---|---|
| `--offset INT` | — | Starting record index (1-based). |
| `--limit INT` | `25` | Records per page. API maximum is 25. |

### Filtering

| Option | Description |
|---|---|
| `--name TEXT` | Audit log notification event name. |
| `--event-id ID` | Event ID. |
| `--category` | `INFO`, `WARN`, `ERROR`, `ALERT`, `TASK_PROGRESS`, `TASK_FAILURE`, `TASK_COMPLETE`, `COMMAND`, `QUERY`, `CONVERSATION` |
| `--severity 1-5` | 1 = highest severity, 5 = lowest. |
| `--domain TEXT` | Event domain. |
| `--sub-domain TEXT` | Event sub-domain. |
| `--source TEXT` | Event source. |
| `--user-id ID` | User ID. |
| `--context TEXT` | Correlation ID. |
| `--event-hierarchy TEXT` | Hierarchy path, e.g. `US.CA.San Jose`. |
| `--site-id ID` | Site ID. |
| `--device-id ID` | Device ID. |
| `--parent-instance-id ID` | Parent instance ID. |
| `--instance-id ID` | Instance ID. |
| `--is-system-events` | Filter to system-generated events only. |
| `--description TEXT` | Case-insensitive partial/full search on description. |

### Sorting

| Option | Description |
|---|---|
| `--sort-by FIELD` | Field name to sort results by. |
| `--order asc\|desc` | Sort direction. Server default is `desc` (newest first). |

### Output

| Option | Default | Description |
|---|---|---|
| `--output-file FILE` | `{datetime}_audit_log` | Base file path (no extension). Extension is appended based on format. |
| `--output-format csv\|json\|both` | `csv` | Output format. |
| `--no-progress` | *(progress enabled)* | Suppress the real-time fetch progress line. |

---

## Examples

```bash
# Last 30 days — CSV output, auto-generated filename
python catc_auditreport.py --period 30d

# Last 24 hours — filter login events, save both CSV and JSON
python catc_auditreport.py --period 24h --name LOGIN_USER_EVENT --output-format both

# Specific time range — JSON only, custom filename
python catc_auditreport.py --start-time 1597950637211 --end-time 1597961437211 \
    --output-format json --output-file reports/audit_jan

# Filter by category and severity — single page, no progress output
python catc_auditreport.py --category TASK_FAILURE --severity 1 \
    --limit 25 --no-progress

# Last 7 days — save to a subfolder
python catc_auditreport.py --period 7d --output-format both \
    --output-file exports/weekly_audit
```

---

## Output

### CSV

- Fields `timestamp`, `startTime`, `endTime` are converted from epoch milliseconds to `YYYY-MM-DD HH:MM:SS.ffffff UTC`.
- Nested `dict`/`list` values are serialised as JSON strings.
- `null` values are written as empty strings.
- Column order follows the first record's key order.

### JSON

Pretty-printed with 2-space indentation, UTF-8 encoded.

---

## Progress Output

When fetching with auto-pagination, a single line is updated in-place:

```
Fetching audit logs (limit=25 per page)...
Page 12 | +25 records | Total: 300
...
Done: 6225 record(s) retrieved across 249 page(s).
```

Use `--no-progress` to suppress this (e.g. when redirecting stdout to a file).

---

## Logging

Detailed debug logs are written to `logs/application_run.log` (max 50 MB, rotated automatically). This includes:

- Each paginated request with offset/limit
- API response diagnostics (status code, Content-Type, body preview) on parse failures
- Rate limiting sleep events
- Token refresh events

---

## Project Structure

```
catc-auditreport/
├── catc_auditreport.py      # Main CLI script
├── catc_config.py           # CATC IP and port configuration
└── shared_utils/
    ├── catc_restapi_lib.py  # REST API client (CatcRestApiClient)
    ├── log_setup.py         # Logging configuration helper
    ├── util.py              # CSV/dict utility functions
    ├── README.md            # shared_utils library documentation
    ├── CHANGELOG.md         # shared_utils changelog
    └── MIGRATION_GUIDE.md   # Migration guide from DNAC to CATC naming
```

---

## API Reference

**Endpoint used:** `GET /dna/data/api/v1/event/event-series/audit-logs`

Pagination is offset-based. The API maximum page size is 25 records. When a time range is provided, the tool automatically iterates pages until a short or empty batch is returned.

---

## License

Copyright (c) 2021–2026 Cisco and/or its affiliates.  
Licensed under the [Cisco Sample Code License, Version 1.1](https://developer.cisco.com/docs/licenses).
