import json
from dataclasses import dataclass

from bench.issue import decode_bench_body
from bench.paths import resolve_relative
from processing import proofs
from processing.intake import get_received
from report.receipt import FirstReceipt, load_first_receipt
from report.snapshots import ReportSnapshot, load_snapshot
from storage import positive_id, sequence
from template.calibration import decide_zero
from template.issue import decode_template_body


@dataclass(frozen=True)
class ReadReport:
    snapshot: ReportSnapshot
    first_receipt: FirstReceipt


def read(db, report_id):
    positive_id(report_id, 'report ID')
    snapshot = load_snapshot(db, report_id)
    return ReadReport(snapshot, load_first_receipt(db, report_id))


def _ordinals(ordinals, count):
    order = list(sequence(ordinals, 'disclosure ordinals'))
    for ordinal in order:
        if type(ordinal) is not int or ordinal < 1 or ordinal > count:
            raise ValueError(f'disclosure ordinal {ordinal!r} is outside the report')
    if len(set(order)) != len(order):
        raise ValueError('disclosure ordinals must not repeat')
    return order


def _v2(package, kind):
    if package.envelope.version != 2:
        raise ValueError(f'selected row references a version 1 {kind} issue')
    return package.envelope


def _template_record(envelope, row):
    frozen = decode_template_body(envelope.body)
    if type(row.template_row) is not int or row.template_row < 1 or row.template_row > len(frozen.rows):
        raise ValueError(f'report row {row.template_row!r} is outside the template issue')
    return frozen, frozen.rows[row.template_row - 1].to_record()


def _bench_proof(envelope, target):
    frozen = decode_bench_body(envelope.body)
    return {
        'path': target,
        'siblings': proofs.bench_proof(envelope.number, frozen.to_record()['entries'], target),
    }


def _matches(row, template_row, zero):
    return (
        row.source == template_row.source
        and row.raw_strength == template_row.raw_strength
        and row.reference == template_row.reference
        and row.reference_source == template_row.reference_source
        and row.zero == zero
    )


def _disclosure_row(db, ordinal, row):
    template = _v2(get_received(db, row.template_receipt, kind='template'), 'template')
    bench = _v2(get_received(db, row.bench_receipt, kind='bench'), 'bench')
    frozen_template, template_record = _template_record(template, row)
    frozen_bench = decode_bench_body(bench.body)
    if (row.template, row.template_revision) != (frozen_template.name, frozen_template.revision):
        raise ValueError(f'report row {ordinal} does not belong to its template issue')
    if (row.bench, row.bench_revision) != (frozen_bench.bench, frozen_bench.revision):
        raise ValueError(f'report row {ordinal} does not belong to its bench issue')

    target = resolve_relative(row.mount, row.reference)
    entry = frozen_bench.entries.get(target)
    entry_record = None if entry is None else entry.to_record()
    original = frozen_template.rows[row.template_row - 1]
    if not _matches(row, original, decide_zero(target, entry, original.default)):
        raise ValueError(f'report row {ordinal} no longer matches its frozen inputs')

    return {
        'ordinal': ordinal,
        'template_number': template.number,
        'template_row': row.template_row,
        'bench_number': bench.number,
        'mount': row.mount,
        'template': template_record,
        'template_proof': {
            'index': row.template_row,
            'count': len(frozen_template.rows),
            'siblings': proofs.template_proof(template.number, frozen_template.to_record()['rows'], row.template_row),
        },
        'entry': entry_record,
        'bench_proof': _bench_proof(bench, target),
    }


def disclose(db, report_id, ordinals):
    """Export selected signed rows, with proofs, as UTF-8 JSON bytes."""
    positive_id(report_id, 'report ID')
    snapshot = load_snapshot(db, report_id)
    order = _ordinals(ordinals, len(snapshot.rows))
    rows = [
        _disclosure_row(db, ordinal, snapshot.rows[ordinal - 1])
        for ordinal in order
    ]
    return json.dumps({'report_id': report_id, 'rows': rows}, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')
