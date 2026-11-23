"""Shared bookkeeping for issued template and bench packages."""


def ensure_issue_table(db, table):
    columns = db.execute(f'PRAGMA table_info({table})').fetchall()
    if not columns:
        db.execute(f'''
            CREATE TABLE {table} (
                number TEXT PRIMARY KEY NOT NULL,
                version INTEGER NOT NULL,
                packet BLOB NOT NULL
            )
        ''')
    elif 'version' not in {row[1] for row in columns}:
        db.execute(f'ALTER TABLE {table} ADD COLUMN version INTEGER NOT NULL DEFAULT 1')


def load_issued(db, table, number):
    return db.execute(
        f'SELECT version, packet FROM {table} WHERE number = ?', (number,)
    ).fetchone()


def store_issued(db, table, number, version, packet):
    db.execute(
        f'INSERT INTO {table} (number, version, packet) VALUES (?, ?, ?)',
        (number, version, packet),
    )
