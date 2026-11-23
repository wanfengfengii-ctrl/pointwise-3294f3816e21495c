from dataclasses import dataclass

from processing.results import ResultRow
from storage import canonical_json, decode_integer, encode_integer, has_table, parse_json


@dataclass(frozen=True)
class ReportSnapshot:
    report_id: int
    rows: tuple[ResultRow, ...]
    total: int


def ensure_snapshot_tables(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS report_snapshot (
            report_id INTEGER PRIMARY KEY,
            total TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS report_rows (
            report_id INTEGER NOT NULL REFERENCES report_snapshot(report_id),
            ordinal INTEGER NOT NULL CHECK (ordinal > 0),
            body TEXT NOT NULL,
            PRIMARY KEY (report_id, ordinal)
        )
    ''')


def store_snapshot(db, rows, total):
    if not db.in_transaction:
        raise ValueError('snapshot must be written inside a publication transaction')
    cursor = db.execute('INSERT INTO report_snapshot (total) VALUES (?)', (encode_integer(total),))
    report_id = cursor.lastrowid
    db.executemany(
        'INSERT INTO report_rows VALUES (?, ?, ?)',
        (
            (report_id, ordinal, canonical_json(row.to_record()))
            for ordinal, row in enumerate(rows, start=1)
        ),
    )
    return ReportSnapshot(report_id, rows, total)


def load_snapshot(db, report_id):
    header = None
    if has_table(db, 'report_snapshot'):
        header = db.execute('SELECT total FROM report_snapshot WHERE report_id = ?', (report_id,)).fetchone()
    if header is None:
        raise KeyError(f'unknown report {report_id}')
    records = db.execute(
        'SELECT body FROM report_rows WHERE report_id = ? ORDER BY ordinal', (report_id,)
    )
    rows = tuple(ResultRow.from_record(parse_json(record[0])) for record in records)
    return ReportSnapshot(report_id, rows, decode_integer(header[0]))
