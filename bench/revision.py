from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from bench.entries import BenchEntry, decode_entries, validate_entries
from storage import ConflictError, canonical_json, fields, has_table, parse_json, text, write_transaction


@dataclass(frozen=True)
class BenchRevision:
    bench: str
    revision: str
    entries: Mapping[str, BenchEntry]

    def to_record(self):
        return {
            'bench': self.bench,
            'revision': self.revision,
            'entries': [self.entries[path].to_record() for path in sorted(self.entries)],
        }

    @classmethod
    def from_record(cls, record):
        fields(record, ('bench', 'revision', 'entries'), label='bench revision')
        bench = text(record['bench'], 'bench name')
        revision = text(record['revision'], 'bench revision')
        entries = decode_entries(bench, revision, record['entries'])
        return cls(bench, revision, MappingProxyType(entries))


def freeze_bench(db, bench, revision, rows):
    text(bench, 'bench name')
    text(revision, 'bench revision')
    frozen = BenchRevision(bench, revision, MappingProxyType(validate_entries(bench, revision, rows)))
    body = canonical_json(frozen.to_record())
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS bench_revision (
                bench TEXT NOT NULL,
                revision TEXT NOT NULL,
                body TEXT NOT NULL,
                PRIMARY KEY (bench, revision)
            )
        ''')
        cursor = db.execute(
            'INSERT INTO bench_revision VALUES (?, ?, ?) ON CONFLICT (bench, revision) DO NOTHING',
            (bench, revision, body),
        )
        if cursor.rowcount != 1:
            raise ConflictError(f'bench revision already exists: {bench!r}, {revision!r}')
    return frozen


def get_bench_revision(db, bench, revision):
    text(bench, 'bench name')
    text(revision, 'bench revision')
    row = None
    if has_table(db, 'bench_revision'):
        row = db.execute(
            'SELECT body FROM bench_revision WHERE bench = ? AND revision = ?', (bench, revision)
        ).fetchone()
    if row is None:
        raise KeyError(f'unknown bench revision {bench!r}, {revision!r}')
    return BenchRevision.from_record(parse_json(row[0]))
