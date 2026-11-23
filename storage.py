import json
from contextlib import contextmanager


class ConflictError(ValueError):
    pass


def fields(record, required, optional=(), *, label='record'):
    if not isinstance(record, dict):
        raise ValueError(f'{label} must be an object')
    keys = record.keys()
    if not set(required) <= keys or not keys <= set(required) | set(optional):
        raise ValueError(f'invalid fields for {label}')
    return record


def text(value, label):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{label} must be nonblank text without NUL')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{label} must be valid Unicode') from exc
    return value


def sequence(value, label, *, allow_empty=False):
    if not isinstance(value, (tuple, list)) or (not value and not allow_empty):
        raise ValueError(f'{label} must be an ordered sequence')
    return value


def integer(value, label):
    if type(value) is not int:
        raise ValueError(f'{label} must be an integer')
    return value


def positive_id(value, label):
    if integer(value, label) <= 0 or value > (1 << 63) - 1:
        raise ValueError(f'{label} is outside the SQLite identifier range')
    return value


def encode_integer(value):
    return format(integer(value, 'strength or zero'), 'x')


def decode_integer(value):
    if not isinstance(value, str):
        raise ValueError('encoded integer must be text')
    try:
        number = int(value, 16)
    except ValueError as exc:
        raise ValueError('invalid encoded integer') from exc
    if encode_integer(number) != value:
        raise ValueError('encoded integer is outside canonical form')
    return number


def canonical_json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':'))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def _invalid_constant(token):
    raise ValueError(f'invalid JSON constant {token}')


def parse_json(data):
    return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def has_table(db, name):
    return db.execute(
        'SELECT 1 FROM main.sqlite_schema WHERE type = ? AND name = ?', ('table', name)
    ).fetchone() is not None


@contextmanager
def write_transaction(db):
    if db.in_transaction:
        raise ValueError('business write requires a connection outside an existing transaction')
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise
