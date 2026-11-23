from dataclasses import dataclass

from bench.paths import normalize_entry_path
from storage import fields, text


@dataclass(frozen=True)
class BenchEvidence:
    bench: str
    revision: str
    path: str
    source: str

    @classmethod
    def from_record(cls, record):
        fields(record, ('bench', 'revision', 'path', 'source'), label='bench evidence')
        return make_bench_evidence(**record)


def make_bench_evidence(bench, revision, path, source):
    return BenchEvidence(
        text(bench, 'bench name'),
        text(revision, 'bench revision'),
        normalize_entry_path(path),
        text(source, 'bench entry source'),
    )
