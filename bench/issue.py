from bench.revision import BenchRevision, get_bench_revision
from processing.envelopes import encode_envelope, issue_number, verify_envelope
from storage import write_transaction


def decode_bench_body(body):
    return BenchRevision.from_record(body)


def issue_bench(db, bench, revision):
    number = issue_number(bench, revision)
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS bench_issue (
                number TEXT PRIMARY KEY NOT NULL,
                packet BLOB NOT NULL
            )
        ''')
        existing = db.execute('SELECT packet FROM bench_issue WHERE number = ?', (number,)).fetchone()
        if existing is not None:
            return verify_envelope(existing[0])
        frozen = get_bench_revision(db, bench, revision)
        packet = encode_envelope('bench', number, frozen.to_record())
        envelope = verify_envelope(packet)
        db.execute('INSERT INTO bench_issue VALUES (?, ?)', (number, packet))
    return envelope
