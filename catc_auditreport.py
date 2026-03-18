from shared_utils.catc_restapi_lib import CatcRestApiClient
from shared_utils.log_setup import log_setup
from shared_utils.util import csv_to_dict, dict_to_csv, list_dict_to_csv, print_csv
from catc_config import CATC_IP, CATC_PORT
import logging
import json
import csv
import argparse
from argparse import RawTextHelpFormatter
import getpass
import time
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# Supported period units
PERIOD_RE = re.compile(r'^(\d+)(d|h|m)$', re.IGNORECASE)
PERIOD_UNITS_TO_SECONDS = {'d': 86400, 'h': 3600, 'm': 60}


def render_progress_line(message: str, finalize: bool = False) -> None:
    """Render one progress line by overwriting the current terminal line.

    Padding to terminal width ensures older text is fully cleared when the
    next message is shorter.
    """
    if not sys.stdout.isatty():
        print(message)
        return

    terminal_width = max(shutil.get_terminal_size(fallback=(120, 20)).columns, 20)
    safe_message = message[:terminal_width - 1].ljust(terminal_width - 1)
    sys.stdout.write(f'\r{safe_message}')
    if finalize:
        sys.stdout.write('\n')
    sys.stdout.flush()


def parse_period(period_str: str):
    """Validate and parse a period string such as '30d', '24h', '90m'.

    Args:
        period_str: Period string with a numeric value and a unit suffix
                    d = days, h = hours, m = minutes.

    Returns:
        The original string if valid (epoch calculation happens in main()).

    Raises:
        argparse.ArgumentTypeError: If the format is invalid.
    """
    match = PERIOD_RE.match(period_str.strip())
    if not match:
        raise argparse.ArgumentTypeError(
            f"Invalid period '{period_str}'. "
            "Use format: <number><unit> where unit is d (days), h (hours), "
            "or m (minutes). Examples: 30d, 24h, 90m."
        )
    return period_str.strip().lower()


def period_to_epoch_ms(period_str: str):
    """Convert a validated period string to (start_time_ms, end_time_ms).

    end_time_ms is the current time; start_time_ms is end_time_ms minus the period.

    Args:
        period_str: Validated period string (e.g. '30d', '24h', '90m').

    Returns:
        Tuple of (start_time_ms, end_time_ms) as integers.
    """
    match = PERIOD_RE.match(period_str)
    assert match is not None, f"period_to_epoch_ms called with unvalidated period: '{period_str}'"
    value, unit = int(match.group(1)), match.group(2).lower()
    delta_seconds = value * PERIOD_UNITS_TO_SECONDS[unit]
    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (delta_seconds * 1000)
    logging.debug(
        f"Period '{period_str}' resolved to start_time={start_time_ms} "
        f"end_time={end_time_ms} (delta={delta_seconds}s)."
    )
    return start_time_ms, end_time_ms


def fetch_all_audit_logs(catc: CatcRestApiClient, args: argparse.Namespace,
                         start_time: int, end_time: int,
                         show_progress: bool = True):
    """Paginate through all audit log records within the given time window.

    Calls get_audit_log_records() repeatedly, incrementing offset by limit=25
    on each iteration, until the API returns fewer records than the limit
    (signalling the last page) or returns None (error).

    Args:
        catc: Authenticated CatcRestApiClient instance.
        args: Parsed CLI arguments used for filter parameters.
        start_time: Start time in milliseconds since epoch.
        end_time: End time in milliseconds since epoch.
        show_progress: Print per-page and summary progress to stdout.

    Returns:
        List of all collected audit log records across all pages.
    """
    all_records = []
    offset = 0
    limit = 25
    page = 1

    logging.info(
        f'Starting paginated audit log fetch '
        f'(start_time={start_time}, end_time={end_time}).'
    )
    if show_progress:
        render_progress_line(f'Fetching audit logs (limit={limit} per page)...')

    while True:
        logging.info(f'Fetching audit log page {page} (offset={offset}, limit={limit})...')

        batch = catc.get_audit_log_records(
            parent_instance_id=args.parent_instance_id,
            instance_id=args.instance_id,
            name=args.name,
            event_id=args.event_id,
            category=args.category,
            severity=args.severity,
            domain=args.domain,
            sub_domain=args.sub_domain,
            source=args.source,
            user_id=args.user_id,
            context=args.context,
            event_hierarchy=args.event_hierarchy,
            site_id=args.site_id,
            device_id=args.device_id,
            is_system_events=args.is_system_events if args.is_system_events else None,
            description=args.description,
            offset=offset,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
            sort_by=args.sort_by,
            order=args.order
        )

        if batch is None:
            logging.warning(f'Page {page} returned None. Stopping pagination.')
            if show_progress:
                render_progress_line(f'No response on page {page}. Stopping.', finalize=True)
            break

        batch_list = batch if isinstance(batch, list) else [batch]

        if not batch_list:
            logging.info(f'Page {page} returned 0 records. Pagination complete.')
            if show_progress:
                render_progress_line(f'Page {page}: 0 records returned. Done.', finalize=True)
            break

        all_records.extend(batch_list)
        logging.info(
            f'Page {page}: retrieved {len(batch_list)} record(s). '
            f'Running total: {len(all_records)}.'
        )
        if show_progress:
            render_progress_line(
                f'Page {page} | +{len(batch_list)} records | Total: {len(all_records)}'
            )
        logging.debug(f'Page {page} records: {json.dumps(batch_list, indent=2)}')

        if len(batch_list) < limit:
            logging.info(
                f'Page {page} returned {len(batch_list)} record(s) '
                f'(< limit {limit}). Last page reached. Pagination complete.'
            )
            break

        offset += limit
        page += 1

    logging.info(f'Pagination finished. Total records collected: {len(all_records)}.')
    if show_progress:
        render_progress_line(
            f'Done: {len(all_records)} record(s) retrieved across {page} page(s).',
            finalize=True
        )
    return all_records


def get_output_file_base(output_file: str | None) -> Path:
    """Resolve base output file path for audit log export."""
    if output_file:
        output_path = Path(output_file)
        return output_path.with_suffix('') if output_path.suffix else output_path

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return Path(f'{timestamp}_audit_log')


def convert_epoch_ms_to_datetime(value):
    """Convert epoch milliseconds to a readable UTC datetime string."""
    if not isinstance(value, (int, float)):
        return value

    # Typical epoch millisecond values are 13 digits.
    if value < 10**11:
        return value

    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f UTC')
    except (OverflowError, OSError, ValueError):
        return value


def normalize_audit_log_record(record: dict) -> dict:
    """Prepare a single audit log record for CSV output."""
    normalized_record = {}

    for key, value in record.items():
        if key in {'timestamp', 'startTime', 'endTime'}:
            normalized_record[key] = convert_epoch_ms_to_datetime(value)
        elif isinstance(value, (dict, list)):
            normalized_record[key] = json.dumps(value, ensure_ascii=False)
        elif value is None:
            normalized_record[key] = ''
        else:
            normalized_record[key] = value

    return normalized_record


def save_audit_logs_csv(audit_logs, output_file: str | None) -> Path:
    """Persist audit logs to a CSV file and return the path."""
    output_path = get_output_file_base(output_file).with_suffix('.csv')
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = audit_logs if isinstance(audit_logs, list) else [audit_logs]
    normalized_rows = [normalize_audit_log_record(row) for row in rows if isinstance(row, dict)]

    if not normalized_rows:
        raise ValueError('No audit log records available to write to CSV.')

    fieldnames = []
    for row in normalized_rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with output_path.open('w', encoding='utf-8', newline='') as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(normalized_rows)

    logging.info(f'Audit logs saved to CSV: {output_path}')
    return output_path


def save_audit_logs_json(audit_logs, output_file: str | None) -> Path:
    """Persist audit logs to a JSON file and return the path."""
    output_path = get_output_file_base(output_file).with_suffix('.json')
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open('w', encoding='utf-8') as file_handle:
        json.dump(audit_logs, file_handle, indent=2, ensure_ascii=False)

    logging.info(f'Audit logs saved to JSON: {output_path}')
    return output_path


def save_audit_logs(audit_logs, output_file: str | None, output_format: str) -> list[Path]:
    """Persist audit logs in CSV, JSON, or both formats."""
    saved_paths = []

    if output_format in {'csv', 'both'}:
        saved_paths.append(save_audit_logs_csv(audit_logs, output_file))

    if output_format in {'json', 'both'}:
        saved_paths.append(save_audit_logs_json(audit_logs, output_file))

    return saved_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Retrieve Audit Log records from Cisco Catalyst Center.\n\n'
            'Endpoint: GET /dna/data/api/v1/event/event-series/audit-logs\n\n'
            'Time range options (mutually exclusive):\n'
            '  --period      Relative period from now, e.g. 30d, 24h, 90m.\n'
            '                Automatically paginates to collect ALL records.\n'
            '  --start-time / --end-time\n'
            '                Absolute epoch-ms timestamps (both required together).\n'
            '                Automatically paginates to collect ALL records.\n\n'
            'Without any time range option a single API call is made with\n'
            'the --limit and --offset values provided.'
        ),
        formatter_class=RawTextHelpFormatter
    )

    # --- Pagination ---
    pagination = parser.add_argument_group('Pagination')
    pagination.add_argument(
        '--offset', type=int, default=None,
        help='Position of the first record to return (1-based index).'
    )
    pagination.add_argument(
        '--limit', type=int, default=25,
        help='Number of records per page. Maximum allowed by API is 25 (default: 25).'
    )

    # --- Filtering ---
    filtering = parser.add_argument_group('Filtering')
    filtering.add_argument(
        '--parent-instance-id', type=str, default=None,
        metavar='ID',
        help="Parent audit log record's instanceID."
    )
    filtering.add_argument(
        '--instance-id', type=str, default=None,
        metavar='ID',
        help='InstanceID of the audit log.'
    )
    filtering.add_argument(
        '--name', type=str, default=None,
        help='Audit log notification event name.'
    )
    filtering.add_argument(
        '--event-id', type=str, default=None,
        metavar='ID',
        help="Audit log notification's event ID."
    )
    filtering.add_argument(
        '--category', type=str, default=None,
        choices=['INFO', 'WARN', 'ERROR', 'ALERT',
                 'TASK_PROGRESS', 'TASK_FAILURE', 'TASK_COMPLETE',
                 'COMMAND', 'QUERY', 'CONVERSATION'],
        help="Audit log notification's event category."
    )
    filtering.add_argument(
        '--severity', type=str, default=None,
        choices=['1', '2', '3', '4', '5'],
        help="Audit log notification's event severity (1=highest, 5=lowest)."
    )
    filtering.add_argument(
        '--domain', type=str, default=None,
        help="Audit log notification's event domain."
    )
    filtering.add_argument(
        '--sub-domain', type=str, default=None,
        metavar='SUBDOMAIN',
        help="Audit log notification's event sub-domain."
    )
    filtering.add_argument(
        '--source', type=str, default=None,
        help="Audit log notification's event source."
    )
    filtering.add_argument(
        '--user-id', type=str, default=None,
        metavar='ID',
        help="Audit log notification's userId."
    )
    filtering.add_argument(
        '--context', type=str, default=None,
        help="Audit log notification's event correlationId."
    )
    filtering.add_argument(
        '--event-hierarchy', type=str, default=None,
        metavar='HIERARCHY',
        help='Event hierarchy (e.g. "US.CA.San Jose"). Delimiter is ".".'
    )
    filtering.add_argument(
        '--site-id', type=str, default=None,
        metavar='ID',
        help="Audit log notification's siteId."
    )
    filtering.add_argument(
        '--device-id', type=str, default=None,
        metavar='ID',
        help="Audit log notification's deviceId."
    )
    filtering.add_argument(
        '--is-system-events', action='store_true', default=None,
        help='Filter to system-generated audit logs only.'
    )
    filtering.add_argument(
        '--description', type=str, default=None,
        help='Case-insensitive partial/full string search on the description field.'
    )

    # --- Time range (mutually exclusive: --period  vs  --start-time/--end-time) ---
    time_range = parser.add_argument_group(
        'Time Range',
        'Use --period for a relative window OR --start-time + --end-time for an '
        'absolute window. These options are mutually exclusive.'
    )
    time_range.add_argument(
        '--period', type=parse_period, default=None,
        metavar='PERIOD',
        help=(
            'Relative time period ending now.\n'
            'Format: <number><unit>  where unit is:\n'
            '  d = days   (e.g. 30d, 7d, 1d)\n'
            '  h = hours  (e.g. 24h, 12h, 1h)\n'
            '  m = minutes (e.g. 90m, 60m)\n'
            'Automatically paginates to collect ALL logs in the window.'
        )
    )
    time_range.add_argument(
        '--start-time', type=int, default=None,
        metavar='MS_EPOCH',
        help=(
            'Start time in milliseconds since epoch (e.g. 1597950637211).\n'
            'Must be used together with --end-time.\n'
            'Automatically paginates to collect ALL logs in the window.'
        )
    )
    time_range.add_argument(
        '--end-time', type=int, default=None,
        metavar='MS_EPOCH',
        help=(
            'End time in milliseconds since epoch (e.g. 1597961437211).\n'
            'Must be used together with --start-time.'
        )
    )

    # --- Sorting ---
    sorting = parser.add_argument_group('Sorting')
    sorting.add_argument(
        '--sort-by', type=str, default=None,
        metavar='FIELD',
        help='Field name to sort the audit log records by.'
    )
    sorting.add_argument(
        '--order', type=str, default=None,
        choices=['asc', 'desc'],
        help='Sort order. Default on the server side is desc (newest first).'
    )

    output = parser.add_argument_group('Output')
    output.add_argument(
        '--output-file', type=str, default=None,
        metavar='FILE',
        help=(
            'Base output file path. Extension is chosen from --output-format. If not '
            'provided, the file name defaults to "{datetime}_audit_log" in the '
            'current working directory.'
        )
    )
    output.add_argument(
        '--output-format', type=str, default='csv',
        choices=['csv', 'json', 'both'],
        help='Output format to save: csv, json, or both (default: csv).'
    )
    output.add_argument(
        '--no-progress', action='store_false', dest='progress',
        help='Disable on-screen progress output during paginated fetch (enabled by default).'
    )

    return parser.parse_args()


def main():
    log_setup(
        log_level=logging.DEBUG,
        log_file='logs/application_run.log',
        log_term=False,
        max_bytes=50*1024*1024  # 50MB
    )
    logging.info('Starting the program.')

    args = parse_args()
    logging.debug(f'Parsed arguments: {vars(args)}')

    # --- Validate time range arguments ---
    if args.period and (args.start_time is not None or args.end_time is not None):
        logging.error('--period cannot be used together with --start-time/--end-time.')
        raise SystemExit('Error: --period cannot be combined with --start-time/--end-time.')

    if (args.start_time is None) != (args.end_time is None):
        logging.error('--start-time and --end-time must both be provided together.')
        raise SystemExit('Error: --start-time and --end-time must be used together.')

    # --- Resolve effective time window ---
    use_pagination = False
    start_time = args.start_time
    end_time = args.end_time

    if args.period:
        start_time, end_time = period_to_epoch_ms(args.period)
        logging.info(
            f"Period '{args.period}' resolved: "
            f'start_time={start_time}, end_time={end_time}.'
        )
        use_pagination = True
    elif start_time is not None and end_time is not None:
        logging.info(
            f'Using explicit time range: start_time={start_time}, end_time={end_time}.'
        )
        use_pagination = True

    print('='*20)
    username = input('Username: ')
    password = getpass.getpass()
    print('='*20)

    catc = CatcRestApiClient(CATC_IP, CATC_PORT, username, password)

    try:
        if use_pagination:
            # --- Auto-paginate: collect ALL records within the time window ---
            logging.info(
                f'Paginated fetch enabled '
                f'(category={args.category}, severity={args.severity}, '
                f'start_time={start_time}, end_time={end_time}).'
            )
            audit_logs = fetch_all_audit_logs(catc, args, start_time, end_time,
                                               show_progress=args.progress)

            if audit_logs:
                logging.info(
                    f'Paginated fetch complete. '
                    f'Total records retrieved: {len(audit_logs)}.'
                )
                logging.debug(
                    f'All audit log records: {json.dumps(audit_logs, indent=2)}'
                )
                output_paths = save_audit_logs(
                    audit_logs,
                    args.output_file,
                    args.output_format
                )
                print('Audit logs saved to ' + ', '.join(str(path) for path in output_paths))
            else:
                logging.warning(
                    'Paginated fetch returned no records for the specified time window.'
                )

        else:
            # --- Single call: use supplied limit/offset as-is ---
            logging.info(
                f'Single-page fetch '
                f'(limit={args.limit}, offset={args.offset}, '
                f'category={args.category}, severity={args.severity}).'
            )
            audit_logs = catc.get_audit_log_records(
                parent_instance_id=args.parent_instance_id,
                instance_id=args.instance_id,
                name=args.name,
                event_id=args.event_id,
                category=args.category,
                severity=args.severity,
                domain=args.domain,
                sub_domain=args.sub_domain,
                source=args.source,
                user_id=args.user_id,
                context=args.context,
                event_hierarchy=args.event_hierarchy,
                site_id=args.site_id,
                device_id=args.device_id,
                is_system_events=args.is_system_events if args.is_system_events else None,
                description=args.description,
                offset=args.offset,
                limit=args.limit,
                start_time=None,
                end_time=None,
                sort_by=args.sort_by,
                order=args.order
            )

            if audit_logs is not None:
                record_count = len(audit_logs) if isinstance(audit_logs, list) else 1
                logging.info(
                    f'Successfully retrieved {record_count} audit log record(s).'
                )
                logging.debug(
                    f'Audit log records: {json.dumps(audit_logs, indent=2)}'
                )
                output_paths = save_audit_logs(
                    audit_logs,
                    args.output_file,
                    args.output_format
                )
                print('Audit logs saved to ' + ', '.join(str(path) for path in output_paths))
            else:
                logging.warning(
                    'No audit log records returned or the request failed.'
                )

    finally:
        catc.logout()
        logging.info('Program completed.')


if __name__ == '__main__':
    main()
