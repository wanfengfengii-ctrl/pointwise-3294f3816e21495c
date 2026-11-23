import sqlite3

from processing.results import ApplicationResult
from report.receipt import ensure_receipt_table, find_by_request, store_first_receipt
from report.snapshots import ensure_snapshot_tables, load_snapshot, store_snapshot
from report.totals import calculate_total
from storage import ConflictError, text, write_transaction


class PublishError(RuntimeError):
    pass


def publish(db, request_id, result):
    text(request_id, 'publication request ID')
    if not isinstance(result, ApplicationResult) or not result.rows:
        raise ValueError('publication requires a completed run with at least one row')
    total = calculate_total(result.rows)
    try:
        with write_transaction(db):
            ensure_snapshot_tables(db)
            ensure_receipt_table(db)
            existing = find_by_request(db, request_id)
            if existing is not None:
                snapshot = load_snapshot(db, existing.report_id)
                if (snapshot.rows, snapshot.total) != (result.rows, total):
                    raise ConflictError(f'publication request {request_id!r} already has a different result')
                receipt = existing
            else:
                snapshot = store_snapshot(db, result.rows, total)
                receipt = store_first_receipt(db, snapshot.report_id, request_id)
    except sqlite3.Error as exc:
        raise PublishError(f'publication failed for {request_id!r}') from exc
    return receipt
