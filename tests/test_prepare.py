import sqlite3
import unittest
from contextlib import closing

from bench.entries import BenchEntryState
from bench.issue import decode_bench_body, issue_bench
from bench.revision import freeze_bench, get_bench_revision
from demo import load_sample
from source.batches import batch_exists, load_batch
from source.ingest import ImportReceipt, ingest
from source.initialize import initialize_source
from template.draft import build_draft
from template.issue import decode_template_body, issue_template
from template.preview import preview
from template.revision import freeze_template, get_template_revision
from tests.helpers import EAST_MOUNT, emit_scenario


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.db = self.enterContext(closing(sqlite3.connect(':memory:')))
        self.sample = load_sample('source.json')
        self.rule = self.sample['template']['rows'][0]

    def prepare_draft(self):
        initialize_source(self.db, self.sample['batches'])
        return build_draft('coat', [self.rule])

    def east_bench(self):
        spec = load_sample('benches.json')[0]
        return freeze_bench(self.db, spec['bench'], spec['revision'], spec['entries'])

    def test_frozen_template_after_preview(self):
        draft = self.prepare_draft()
        trial = preview(self.db, draft, self.east_bench(), EAST_MOUNT)
        self.assertEqual([(row.strength, row.zero.value) for row in trial], [(17, 3)])
        self.assertEqual(trial[0].zero.bench_evidence.source, 'east-log:8')
        freeze_template(self.db, draft, '1')
        draft.replace_rows([{**self.rule, 'measurement_id': 'M2', 'reference': '../new_zero'}])
        freeze_template(self.db, draft, '2')
        first = decode_template_body(issue_template(self.db, 'coat', '1').body)
        second = decode_template_body(issue_template(self.db, 'coat', '2').body)
        row = first.rows[0]
        expected = ['M1', 20, '../zero', 'worksheet/coat:A4', 2, 'worksheet/coat:B4', 'coat-a.csv:2']
        actual = [row.source.measurement_id, row.raw_strength, row.reference, row.reference_source,
                  row.default.value, row.default.source, row.source.locator]
        self.assertEqual(actual, expected)
        self.assertEqual((second.rows[0].source.measurement_id, second.rows[0].reference), ('M2', '../new_zero'))
        emit_scenario(
            'v1', {'raw': 20, 'trial_zero': 3, 'default': 2, 'edited_measurement': 'M2'},
            [17, 3], [trial[0].strength, trial[0].zero.value], expected, actual,
            ['template/preview.py', 'template/revision.py', 'template/issue.py'],
            '20 minus 3 is 17. The issued rule and evidence are the original pre-edit selection.',
        )

    def test_preview_is_read_only(self):
        draft = self.prepare_draft()
        bench = self.east_bench()
        original_rows = draft.rows
        before = tuple(self.db.iterdump())
        self.assertEqual(preview(self.db, draft, bench, EAST_MOUNT)[0].strength, 17)
        with self.assertRaisesRegex(ValueError, 'leaves the bench root'):
            preview(self.db, draft, bench, '')
        self.assertEqual(tuple(self.db.iterdump()), before)
        self.assertEqual(draft.rows, original_rows)

    def test_freeze_preserves_selection(self):
        self.prepare_draft()
        observations = load_batch(self.db, 'run-A')
        self.assertEqual([(row.measurement_id, row.strength, row.source.ordinal) for row in observations],
                         [('M1', 20, 1), ('M2', 20, 2)])
        draft = build_draft('coat', [{**self.rule, 'measurement_id': 'M2'}, self.rule])
        frozen = freeze_template(self.db, draft, 'ordered')
        self.assertEqual(get_template_revision(self.db, 'coat', 'ordered'), frozen)
        issued = decode_template_body(issue_template(self.db, 'coat', 'ordered').body)
        self.assertEqual([(row.source.measurement_id, row.source.locator) for row in issued.rows],
                         [('M2', 'coat-a.csv:3'), ('M1', 'coat-a.csv:2')])
        draft.replace_rows([{**self.rule, 'measurement_id': 'unknown'}])
        with self.assertRaises(KeyError):
            freeze_template(self.db, draft, 'incomplete')
        with self.assertRaises(KeyError):
            get_template_revision(self.db, 'coat', 'incomplete')

    def test_repeat_template_issue(self):
        draft = self.prepare_draft()
        freeze_template(self.db, draft, '1')
        first = issue_template(self.db, 'coat', '1')
        draft.replace_rows([{**self.rule, 'reference': 'different'}])
        freeze_template(self.db, draft, '2')
        second = issue_template(self.db, 'coat', '1')
        self.assertEqual((second.number, second.packet), (first.number, first.packet))
        self.assertNotEqual(issue_template(self.db, 'coat', '2').number, first.number)

    def test_unknown_template_revision(self):
        draft = self.prepare_draft()
        freeze_template(self.db, draft, '1')
        original = issue_template(self.db, 'coat', '1')
        with self.assertRaises(KeyError):
            issue_template(self.db, 'coat', 'unknown')
        self.assertEqual(self.db.execute('SELECT number FROM template_issue').fetchall(), [(original.number,)])

    def test_bench_freeze_and_issue(self):
        rows = [{'path': 'shift/./zero', 'state': 'value', 'value': 0, 'source': 'day-log:1'}]
        frozen = freeze_bench(self.db, 'east', '1', rows)
        original = issue_bench(self.db, 'east', '1')
        rows[0].update(state='disabled', value=None, source='lockout:2')
        freeze_bench(self.db, 'east', '2', rows)
        self.assertEqual(get_bench_revision(self.db, 'east', '1'), frozen)
        self.assertEqual(issue_bench(self.db, 'east', '1').packet, original.packet)
        old_entry = decode_bench_body(original.body).entries['shift/zero']
        new_entry = decode_bench_body(issue_bench(self.db, 'east', '2').body).entries['shift/zero']
        self.assertEqual((old_entry.value, old_entry.evidence.source), (0, 'day-log:1'))
        self.assertEqual((new_entry.state, new_entry.value, new_entry.evidence.revision, new_entry.evidence.source),
                         (BenchEntryState.DISABLED, None, '2', 'lockout:2'))

    def test_bench_duplicate_path(self):
        self.east_bench()
        rows = [
            {'path': 'shift/east/zero', 'state': 'value', 'value': 3, 'source': 'reading:1'},
            {'path': 'shift/east/read/../zero', 'state': 'disabled', 'source': 'lockout:2'},
        ]
        with self.assertRaisesRegex(ValueError, 'duplicate normalized bench path'):
            freeze_bench(self.db, 'east', 'bad', rows)
        with self.assertRaises(KeyError):
            issue_bench(self.db, 'east', 'bad')
        self.assertEqual(decode_bench_body(issue_bench(self.db, 'east', '1').body).entries['shift/east/zero'].value, 3)

    def test_bench_invalid_entry(self):
        for state, value in [('value', True), ('value', None), ('disabled', 1), ('other', 0)]:
            with self.subTest(state=state, value=value):
                with self.assertRaises(ValueError):
                    freeze_bench(self.db, 'east', 'bad', [
                        {'path': 'zero', 'state': state, 'value': value, 'source': 'log:1'}
                    ])
        with self.assertRaises(KeyError):
            issue_bench(self.db, 'east', 'bad')

    def test_duplicate_observation(self):
        self.prepare_draft()
        prior = load_batch(self.db, 'run-A')
        first = {'measurement_id': 'repeat', 'strength': 19, 'source': 'other.csv:1'}
        with self.assertRaisesRegex(ValueError, 'duplicate measurement'):
            ingest(self.db, 'bad', [first, {**first, 'strength': 22, 'source': 'other.csv:2'}])
        self.assertFalse(batch_exists(self.db, 'bad'))
        self.assertEqual(load_batch(self.db, 'run-A'), prior)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_observation').fetchone()[0], 2)

    def test_invalid_read(self):
        self.prepare_draft()
        for invalid in (True, 2.5, '20', None):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'raw strength must be an integer'):
                    ingest(self.db, 'bad', [
                        {'measurement_id': 'first', 'strength': 4, 'source': 'bad.csv:1'},
                        {'measurement_id': 'invalid', 'strength': invalid, 'source': 'bad.csv:2'},
                    ])
                with self.assertRaises(KeyError):
                    load_batch(self.db, 'bad')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_observation').fetchone()[0], 2)

    def test_reinitialize_with_user_batch(self):
        sample_batches = self.sample['batches']
        self.assertEqual(initialize_source(self.db, sample_batches), (ImportReceipt('run-A', 2),))
        ingest(self.db, 'user', [{'measurement_id': 'S', 'strength': 91, 'source': 'user.csv:3'}])
        original = load_batch(self.db, 'user')
        for _ in range(2):
            self.assertEqual(initialize_source(self.db, sample_batches), ())
        self.assertEqual(load_batch(self.db, 'user'), original)
        self.assertEqual(original[0].source.locator, 'user.csv:3')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_batch').fetchone()[0], 2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_observation').fetchone()[0], 3)

    def test_sample_user_collision(self):
        ingest(self.db, 'run-A', [{'measurement_id': 'actual', 'strength': 80, 'source': 'actual.csv:8'}])
        self.assertEqual(initialize_source(self.db, self.sample['batches']), ())
        rows = load_batch(self.db, 'run-A')
        self.assertEqual([(row.measurement_id, row.strength, row.source.locator) for row in rows],
                         [('actual', 80, 'actual.csv:8')])
