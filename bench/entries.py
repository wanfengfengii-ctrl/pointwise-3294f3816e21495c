from dataclasses import dataclass
from enum import StrEnum

from bench.paths import normalize_entry_path
from bench.sources import BenchEvidence, make_bench_evidence
from storage import decode_integer, encode_integer, fields, integer, sequence


class BenchEntryState(StrEnum):
    VALUE = 'value'
    DISABLED = 'disabled'


@dataclass(frozen=True)
class BenchEntry:
    path: str
    state: BenchEntryState
    value: int | None
    evidence: BenchEvidence

    def to_record(self):
        return {
            'path': self.path,
            'state': self.state.value,
            'value': None if self.value is None else encode_integer(self.value),
            'source': self.evidence.source,
        }


def validate_entries(bench, revision, rows):
    entries = {}
    for row in sequence(rows, 'bench entries', allow_empty=True):
        fields(row, ('path', 'state', 'source'), ('value',), label='bench entry')
        path = normalize_entry_path(row['path'])
        if path in entries:
            raise ValueError(f'duplicate normalized bench path {path!r}')
        state = BenchEntryState(row['state'])
        value = row.get('value')
        if state is BenchEntryState.VALUE:
            integer(value, 'bench zero')
        elif value is not None:
            raise ValueError('disabled entry must have an empty value')
        evidence = make_bench_evidence(bench, revision, path, row['source'])
        entries[path] = BenchEntry(path, state, value, evidence)
    return entries


def decode_entries(bench, revision, records):
    rows = []
    for record in sequence(records, 'fixed bench entries', allow_empty=True):
        fields(record, ('path', 'state', 'source', 'value'), label='fixed bench entry')
        path = record['path']
        if normalize_entry_path(path) != path:
            raise ValueError('fixed bench path must be normalized')
        value = record['value']
        rows.append({**record, 'value': None if value is None else decode_integer(value)})
    return validate_entries(bench, revision, rows)
