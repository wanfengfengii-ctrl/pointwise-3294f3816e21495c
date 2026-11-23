import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from bench.issue import issue_bench
from bench.revision import freeze_bench, get_bench_revision
from processing.applications import ApplicationItem
from processing.apply import run
from processing.intake import receive
from report.publish import publish
from report.readback import read
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


if __name__ == '__main__':
    main()
