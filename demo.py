import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from bench.issue import issue_bench
from bench.revision import freeze_bench, get_bench_revision
from processing.applications import ApplicationItem
from processing.apply import run, verify_disclosure
from processing.intake import receive
from report.publish import publish
from report.readback import disclose, read
from source.initialize import initialize_source
from template.draft import build_draft
from template.issue import issue_template
from template.preview import preview
from template.revision import freeze_template


SAMPLES = Path(__file__).resolve().parent / 'samples'


def load_sample(name):
    with (SAMPLES / name).open(encoding='utf-8') as stream:
        return json.load(stream)


def prepare_sample(db, source, benches, trial):
    initialize_source(db, source['batches'])
    spec = source['template']
    draft = build_draft(spec['name'], spec['rows'])
    for bench in benches:
        freeze_bench(db, bench['bench'], bench['revision'], bench['entries'])
    trial_bench = get_bench_revision(db, trial['bench'], trial['revision'])
    trial_rows = preview(db, draft, trial_bench, trial['mount'])
    frozen = freeze_template(db, draft, spec['revision'])
    template = issue_template(db, frozen.name, frozen.revision)
    packages = {
        (bench['bench'], bench['revision']): issue_bench(db, bench['bench'], bench['revision'])
        for bench in benches
    }
    return trial_rows, template, packages


def main():
    source = load_sample('source.json')
    benches = load_sample('benches.json')
    handoff = load_sample('handoff.json')
    with TemporaryDirectory(prefix='spectral-handoff-') as folder:
        author_path = Path(folder) / 'author.sqlite'
        offline_path = Path(folder) / 'offline.sqlite'
        with closing(sqlite3.connect(author_path)) as author:
            trial, template, packages = prepare_sample(author, source, benches, handoff['preview'])
        author_path.unlink()
        print(json.dumps({'preview': [asdict(row) for row in trial]}, ensure_ascii=False, sort_keys=True))
        report_ids = []
        with closing(sqlite3.connect(offline_path)) as offline:
            template_id = receive(offline, template.packet)
            bench_ids = {key: receive(offline, value.packet) for key, value in packages.items()}
            for request in handoff['reports']:
                items = [
                    ApplicationItem(template_id, bench_ids[item['bench'], item['revision']], item['mount'])
                    for item in request['applications']
                ]
                receipt = publish(offline, request['request_id'], run(offline, items))
                report_ids.append(receipt.report_id)
        with closing(sqlite3.connect(offline_path)) as offline:
            for report_id in report_ids:
                print(json.dumps(asdict(read(offline, report_id)), ensure_ascii=False, sort_keys=True))


# ---------------------------------------------------------------------------
# Limited-row disclosure (DISCLOSURE.md): V2 issue -> signed report -> export
# -> database-free review, plus the two rejection demonstrations.
# ---------------------------------------------------------------------------

DISCLOSURE_SELECTION = (1, 3, 5)


def prepare_v2(db, source, benches):
    initialize_source(db, source['batches'])
    spec = source['template']
    first = spec['rows'][0]
    draft = build_draft(spec['name'], [first, {**first, 'measurement_id': 'M2'}])
    freeze_template(db, draft, spec['revision'])
    template = issue_template(db, spec['name'], spec['revision'], version=2)
    packages = {}
    for item in benches:
        freeze_bench(db, item['bench'], item['revision'], item['entries'])
        packages[item['bench'], item['revision']] = issue_bench(
            db, item['bench'], item['revision'], version=2
        )
    return template, packages


def sign_v2(offline, template, packages):
    template_id = receive(offline, template.packet)
    benches = [
        ('east', '1', 'shift/east/read'),
        ('west', 'disabled', 'shift/west/read'),
        ('west', 'missing', 'shift/west/read'),
    ]
    items = [
        ApplicationItem(template_id, receive(offline, packages[bench, revision].packet), mount)
        for bench, revision, mount in benches
    ]
    return publish(offline, 'disclosure-live', run(offline, items)), benches


def disclosure_demo():
    source = load_sample('source.json')
    benches = load_sample('benches.json')
    with TemporaryDirectory(prefix='spectral-disclosure-') as folder:
        author_path = Path(folder) / 'author.sqlite'
        offline_path = Path(folder) / 'offline.sqlite'
        with closing(sqlite3.connect(author_path)) as author:
            template, packages = prepare_v2(author, source, benches)
            anchors = {
                (package.kind, package.number): package.digest
                for package in (template, *packages.values())
            }
        author_path.unlink()
        with closing(sqlite3.connect(offline_path)) as offline:
            receipt, applications = sign_v2(offline, template, packages)
            packet = disclose(offline, receipt.report_id, DISCLOSURE_SELECTION)
            roster = {
                'report_id': receipt.report_id,
                'rows': [
                    {'ordinal': ordinal, 'template_number': template.number, 'template_row': 1,
                     'bench_number': packages[bench, revision].number, 'mount': mount}
                    for ordinal, (bench, revision, mount) in zip(
                        DISCLOSURE_SELECTION, applications, strict=True)
                ],
            }
        print(json.dumps({
            'disclosure': {'report_id': receipt.report_id,
                           'row_identity': [[row['ordinal'], row['template_number'],
                                             row['template_row'], row['bench_number'], row['mount']]
                                            for row in json.loads(packet)['rows']]},
        }, ensure_ascii=False, sort_keys=True))
        reviewed = verify_disclosure(anchors, roster, json.loads(packet))
        print(json.dumps({'review': reviewed}, ensure_ascii=False, sort_keys=True))
        disclosure_demo_rejections(anchors, roster, packet)


def disclosure_demo_rejections(anchors, roster, packet):
    def rejected(label, mutate):
        data = json.loads(packet)
        mutate(data)
        try:
            verify_disclosure(anchors, roster, data)
        except ValueError as exc:
            print(json.dumps({'rejected': label, 'reason': str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            raise RuntimeError(f'disclosure review accepted {label!r}')

    def drop_disabled(data):
        retired = data['rows'][1]
        retired['entry'] = None
        retired['bench_proof'] = data['rows'][2]['bench_proof']

    def write_entry_null(data):
        data['rows'][0]['entry'] = None

    def extra_row(data):
        data['rows'].append(dict(data['rows'][0]))

    rejected('drop-lockout-evidence', drop_disabled)
    rejected('absent-entry-for-present-path', write_entry_null)
    rejected('unapproved-extra-row', extra_row)


if __name__ == '__main__':
    main()
    disclosure_demo()
