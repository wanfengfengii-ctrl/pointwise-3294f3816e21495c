import json
import sqlite3
from contextlib import closing

from bench.issue import issue_bench
from bench.revision import freeze_bench
from demo import load_sample
from processing.applications import ApplicationItem
from processing.apply import run
from processing.intake import receive
from report.publish import publish
from report.readback import read
from source.initialize import initialize_source
from template.draft import build_draft
from template.issue import issue_template
from template.revision import freeze_template


APPLICATIONS = (
    ("east", "1", "shift/east/read"),
    ("west", "disabled", "shift/west/read"),
    ("west", "missing", "shift/west/read"),
)
ORDINALS = (1, 3, 5)
WEST_OTHER_ENTRIES = (
    {"path": "shift/west/a", "state": "value", "value": 91, "source": "maintenance:a"},
    {"path": "shift/west/z", "state": "disabled", "source": "maintenance:z"},
)


def prepare(db, make_template=issue_template, make_bench=issue_bench):
    sample = load_sample("source.json")
    initialize_source(db, sample["batches"])
    spec = sample["template"]
    first = spec["rows"][0]
    draft = build_draft(spec["name"], [first, {**first, "measurement_id": "M2"}])
    freeze_template(db, draft, spec["revision"])
    template = make_template(db, spec["name"], spec["revision"])
    specs = {(item["bench"], item["revision"]): item["entries"] for item in load_sample("benches.json")}
    benches = []
    for bench, revision, _ in APPLICATIONS:
        rows = specs[bench, revision]
        if bench == "west":
            rows = [*rows, *WEST_OTHER_ENTRIES]
        freeze_bench(db, bench, revision, rows)
        benches.append(make_bench(db, bench, revision))
    return template, tuple(benches)


def sign(db, template, benches):
    template_id = receive(db, template.packet)
    items = [
        ApplicationItem(template_id, receive(db, bench.packet), mount)
        for bench, (_, _, mount) in zip(benches, APPLICATIONS, strict=True)
    ]
    return publish(db, "disclosure-sample", run(db, items))


def approval(report_id, template, benches):
    # The approved list travels outside the disclosure packet.
    return {
        "report_id": report_id,
        "rows": [
            {"ordinal": ordinal, "template_number": template.number, "template_row": 1,
             "bench_number": bench.number, "mount": mount}
            for ordinal, bench, (_, _, mount) in zip(ORDINALS, benches, APPLICATIONS, strict=True)
        ],
    }


def issuance_anchors(template, benches):
    return {(item.kind, item.number): item.digest for item in (template, *benches)}


def main():
    with closing(sqlite3.connect(":memory:")) as author:
        template, benches = prepare(author)
    with closing(sqlite3.connect(":memory:")) as handoff:
        receipt = sign(handoff, template, benches)
        signed = read(handoff, receipt.report_id).snapshot
    rows = [signed.rows[ordinal - 1] for ordinal in ORDINALS]
    actual = [(row.source.measurement_id, row.strength, row.zero.kind, row.zero.path) for row in rows]
    expected = [
        ("M1", 17, "bench", "shift/east/zero"),
        ("M1", None, "disabled", "shift/west/zero"),
        ("M1", 18, "default", "shift/west/zero"),
    ]
    if actual != expected or signed.total != 70 or len(signed.rows) != 6:
        raise RuntimeError(f"unexpected V1 signed sample: {actual!r}, total={signed.total}")
    print(json.dumps({"report_id": receipt.report_id, "selected": actual, "signed_total": signed.total}))


if __name__ == "__main__":
    main()
