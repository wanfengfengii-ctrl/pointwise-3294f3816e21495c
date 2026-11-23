from dataclasses import dataclass

from bench.paths import resolve_relative
from bench.revision import BenchRevision
from source.provenance import ObservationSource
from template.calibration import ZeroDecision, decide_zero
from template.draft import select_observations


@dataclass(frozen=True)
class PreviewRow:
    template_row: int
    source: ObservationSource
    raw_strength: int
    strength: int | None
    zero: ZeroDecision


def preview(db, draft, bench_revision, mount):
    if not isinstance(bench_revision, BenchRevision):
        raise ValueError('preview requires a fixed bench revision')
    rows = []
    for position, (rule, observation) in enumerate(select_observations(db, draft), start=1):
        target = resolve_relative(mount, rule.reference)
        zero = decide_zero(target, bench_revision.entries.get(target), rule.default)
        rows.append(PreviewRow(position, observation.source, observation.strength, zero.correct(observation.strength), zero))
    return tuple(rows)
