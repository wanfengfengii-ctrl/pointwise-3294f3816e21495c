from dataclasses import asdict, dataclass

from bench.entries import BenchEntryState
from bench.sources import BenchEvidence
from storage import decode_integer, encode_integer, fields, integer, text


@dataclass(frozen=True)
class DefaultZero:
    value: int
    source: str

    def __post_init__(self):
        integer(self.value, 'default zero')
        text(self.source, 'default zero source')

    def to_record(self):
        return {'value': encode_integer(self.value), 'source': self.source}

    @classmethod
    def from_record(cls, record):
        fields(record, ('value', 'source'), label='fixed default zero')
        return cls(decode_integer(record['value']), record['source'])


@dataclass(frozen=True)
class ZeroDecision:
    kind: str
    path: str
    value: int | None = None
    bench_evidence: BenchEvidence | None = None
    default_source: str | None = None

    def correct(self, raw_strength):
        if self.value is None:
            return None
        return raw_strength - self.value

    def to_record(self):
        record = asdict(self)
        if self.value is not None:
            record['value'] = encode_integer(self.value)
        return record

    @classmethod
    def from_record(cls, record):
        value = record['value']
        evidence = record['bench_evidence']
        return cls(
            record['kind'],
            record['path'],
            None if value is None else decode_integer(value),
            None if evidence is None else BenchEvidence.from_record(evidence),
            record['default_source'],
        )


def decide_zero(path, entry, default):
    if entry is not None:
        if entry.state is BenchEntryState.DISABLED:
            return ZeroDecision('disabled', path, bench_evidence=entry.evidence)
        return ZeroDecision('bench', path, value=entry.value, bench_evidence=entry.evidence)
    if default is not None:
        return ZeroDecision('default', path, value=default.value, default_source=default.source)
    return ZeroDecision('missing', path)
