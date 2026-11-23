from dataclasses import asdict, dataclass

from source.provenance import ObservationSource
from storage import decode_integer, encode_integer
from template.calibration import ZeroDecision


@dataclass(frozen=True)
class ResultRow:
    application_index: int
    template_receipt: int
    bench_receipt: int
    mount: str
    template: str
    template_revision: str
    template_row: int
    bench: str
    bench_revision: str
    source: ObservationSource
    raw_strength: int
    reference: str
    reference_source: str | None
    strength: int | None
    zero: ZeroDecision

    def to_record(self):
        record = asdict(self)
        record['raw_strength'] = encode_integer(self.raw_strength)
        if self.strength is not None:
            record['strength'] = encode_integer(self.strength)
        record['zero'] = self.zero.to_record()
        return record

    @classmethod
    def from_record(cls, record):
        data = dict(record)
        data['source'] = ObservationSource.from_record(data['source'])
        data['raw_strength'] = decode_integer(data['raw_strength'])
        if data['strength'] is not None:
            data['strength'] = decode_integer(data['strength'])
        data['zero'] = ZeroDecision.from_record(data['zero'])
        return cls(**data)


@dataclass(frozen=True)
class ApplicationResult:
    rows: tuple[ResultRow, ...]


def make_result_row(binding, template, bench, position, row, zero):
    return ResultRow(
        application_index=binding.index,
        template_receipt=binding.template.receipt_id,
        bench_receipt=binding.bench.receipt_id,
        mount=binding.mount,
        template=template.name,
        template_revision=template.revision,
        template_row=position,
        bench=bench.bench,
        bench_revision=bench.revision,
        source=row.source,
        raw_strength=row.raw_strength,
        reference=row.reference,
        reference_source=row.reference_source,
        strength=zero.correct(row.raw_strength),
        zero=zero,
    )
