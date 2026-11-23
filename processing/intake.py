from dataclasses import dataclass

from bench.issue import decode_bench_body
from processing.envelopes import Envelope, issue_number, verify_envelope
from storage import ConflictError, has_table, positive_id, write_transaction
from template.issue import decode_template_body


@dataclass(frozen=True)
class ReceivedPackage:
    receipt_id: int
    envelope: Envelope


def _validate_body_identity(envelope):
    if envelope.kind == 'template':
        revision = decode_template_body(envelope.body)
        owner = revision.name
    else:
        revision = decode_bench_body(envelope.body)
        owner = revision.bench
    if issue_number(owner, revision.revision) != envelope.number:
        raise ValueError('package body identity differs from issue number')


def receive(db, packet):
    envelope = verify_envelope(packet)
    _validate_body_identity(envelope)
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS received_package (
                receipt_id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                number TEXT NOT NULL,
                packet BLOB NOT NULL,
                UNIQUE (kind, number)
            )
        ''')
        existing = db.execute(
            'SELECT receipt_id, packet FROM received_package WHERE kind = ? AND number = ?',
            (envelope.kind, envelope.number),
        ).fetchone()
        if existing is not None:
            if existing[1] != envelope.packet:
                raise ConflictError(f'different content for {envelope.kind} issue {envelope.number!r}')
            return existing[0]
        cursor = db.execute(
            'INSERT INTO received_package (kind, number, packet) VALUES (?, ?, ?)',
            (envelope.kind, envelope.number, envelope.packet),
        )
        receipt_id = cursor.lastrowid
    return receipt_id


def get_received(db, receipt_id, *, kind=None):
    positive_id(receipt_id, 'receipt ID')
    row = None
    if has_table(db, 'received_package'):
        row = db.execute(
            'SELECT kind, packet FROM received_package WHERE receipt_id = ?', (receipt_id,)
        ).fetchone()
    if row is None:
        raise KeyError(f'unknown receipt {receipt_id}')
    if kind is not None and row[0] != kind:
        raise ValueError(f'receipt {receipt_id} is {row[0]}, expected {kind}')
    return ReceivedPackage(receipt_id, verify_envelope(row[1]))
