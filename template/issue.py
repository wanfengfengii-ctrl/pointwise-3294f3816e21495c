from processing.envelopes import encode_envelope, issue_number, verify_envelope
from storage import write_transaction
from template.revision import FrozenTemplate, get_template_revision


def decode_template_body(body):
    return FrozenTemplate.from_record(body)


def issue_template(db, name, revision):
    number = issue_number(name, revision)
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS template_issue (
                number TEXT PRIMARY KEY NOT NULL,
                packet BLOB NOT NULL
            )
        ''')
        existing = db.execute('SELECT packet FROM template_issue WHERE number = ?', (number,)).fetchone()
        if existing is not None:
            return verify_envelope(existing[0])
        frozen = get_template_revision(db, name, revision)
        packet = encode_envelope('template', number, frozen.to_record())
        envelope = verify_envelope(packet)
        db.execute('INSERT INTO template_issue VALUES (?, ?)', (number, packet))
    return envelope
