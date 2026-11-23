from bench.issue import decode_bench_body
from bench.paths import resolve_relative
from processing.applications import bind_applications
from processing.results import ApplicationResult, make_result_row
from template.calibration import decide_zero
from template.issue import decode_template_body


def run(db, items):
    rows = []
    for binding in bind_applications(db, items):
        template = decode_template_body(binding.template.envelope.body)
        bench = decode_bench_body(binding.bench.envelope.body)
        for position, row in enumerate(template.rows, start=1):
            path = resolve_relative(binding.mount, row.reference)
            zero = decide_zero(path, bench.entries.get(path), row.default)
            rows.append(make_result_row(binding, template, bench, position, row, zero))
    return ApplicationResult(tuple(rows))
