from dataclasses import dataclass


@dataclass(frozen=True)
class FirstReceipt:
    report_id: int
    request_id: str


def ensure_receipt_table(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS report_first_receipt (
            report_id INTEGER PRIMARY KEY REFERENCES report_snapshot(report_id),
            request_id TEXT NOT NULL UNIQUE
        )
    ''')


def store_first_receipt(db, report_id, request_id):
    if not db.in_transaction:
        raise ValueError('first receipt must be written inside a publication transaction')
    db.execute('INSERT INTO report_first_receipt VALUES (?, ?)', (report_id, request_id))
    return FirstReceipt(report_id, request_id)


def load_first_receipt(db, report_id):
    row = db.execute('SELECT request_id FROM report_first_receipt WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        raise KeyError(f'no first receipt for report {report_id}')
    return FirstReceipt(report_id, row[0])


def find_by_request(db, request_id):
    row = db.execute('SELECT report_id FROM report_first_receipt WHERE request_id = ?', (request_id,)).fetchone()
    if row is None:
        return None
    return FirstReceipt(row[0], request_id)
