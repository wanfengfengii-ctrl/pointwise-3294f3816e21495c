from source.provenance import make_observation_source
from source.records import Observation
from storage import ConflictError, decode_integer, encode_integer, has_table, text, write_transaction


def ensure_batch_tables(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS source_batch (
            batch_id TEXT PRIMARY KEY NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS source_observation (
            batch_id TEXT NOT NULL REFERENCES source_batch(batch_id),
            measurement_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal > 0),
            strength TEXT NOT NULL,
            locator TEXT NOT NULL,
            PRIMARY KEY (batch_id, measurement_id),
            UNIQUE (batch_id, ordinal)
        )
    ''')


def batch_exists(db, batch_id):
    text(batch_id, 'batch ID')
    if not has_table(db, 'source_batch'):
        return False
    return db.execute('SELECT 1 FROM source_batch WHERE batch_id = ?', (batch_id,)).fetchone() is not None


def store_batch(db, batch_id, observations):
    """Store the validated observation sequence for this batch as one unit."""
    with write_transaction(db):
        ensure_batch_tables(db)
        if batch_exists(db, batch_id):
            raise ConflictError(f'batch already exists: {batch_id!r}')
        db.execute('INSERT INTO source_batch VALUES (?)', (batch_id,))
        db.executemany(
            'INSERT INTO source_observation VALUES (?, ?, ?, ?, ?)',
            (
                (batch_id, item.measurement_id, item.source.ordinal, encode_integer(item.strength), item.source.locator)
                for item in observations
            ),
        )


def load_batch(db, batch_id):
    if not batch_exists(db, batch_id):
        raise KeyError(f'unknown batch {batch_id!r}')
    rows = db.execute(
        '''SELECT measurement_id, ordinal, strength, locator FROM source_observation
           WHERE batch_id = ? ORDER BY ordinal''',
        (batch_id,),
    )
    return tuple(
        Observation(decode_integer(strength), make_observation_source(batch_id, measurement, ordinal, locator))
        for measurement, ordinal, strength, locator in rows
    )
