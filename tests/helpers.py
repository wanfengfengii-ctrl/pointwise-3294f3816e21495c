import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from demo import load_sample, prepare_sample
from processing.applications import ApplicationItem
from processing.intake import receive


EAST_MOUNT = 'shift/east/read'
WEST_MOUNT = 'shift/west/read'


def emit_scenario(case_id, input_data, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': input_data,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': paths,
        'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(TemporaryDirectory(prefix='spectral-test-')))
        self.offline_path = self.folder / 'offline.sqlite'
        self.offline = self.open_offline()

    def open_offline(self):
        return self.enterContext(closing(sqlite3.connect(self.offline_path)))

    def reopen_offline(self):
        self.offline.close()
        self.offline = self.open_offline()

    def packets(self, *, default=True):
        source = load_sample('source.json')
        if not default:
            source['template']['revision'] = 'no-default'
            del source['template']['rows'][0]['default']
        author_path = self.folder / 'author.sqlite'
        with closing(sqlite3.connect(author_path)) as author:
            _, template, benches = prepare_sample(
                author, source, load_sample('benches.json'), load_sample('handoff.json')['preview']
            )
        author_path.unlink()
        return template, benches

    def receive_inputs(self, *, default=True):
        template, benches = self.packets(default=default)
        template_id = receive(self.offline, template.packet)
        bench_ids = {key: receive(self.offline, value.packet) for key, value in benches.items()}
        return template_id, bench_ids

    def two_bench_items(self, template_id, bench_ids, west_revision='1'):
        return [
            ApplicationItem(template_id, bench_ids['east', '1'], EAST_MOUNT),
            ApplicationItem(template_id, bench_ids['west', west_revision], WEST_MOUNT),
        ]
