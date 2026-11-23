import sqlite3
from contextlib import closing

from bench.issue import issue_bench
from bench.revision import freeze_bench
from demo import load_sample
from processing.applications import ApplicationItem
from processing.apply import run
from processing.intake import receive
from report.publish import PublishError, publish
from report.readback import read
from source.initialize import initialize_source
from template.draft import build_draft
from template.issue import issue_template
from template.revision import freeze_template
from tests.helpers import EAST_MOUNT, OfflineCase, emit_scenario


class ReportTests(OfflineCase):
    def old_and_new_results(self):
        template, benches = self.receive_inputs()
        east, west = self.two_bench_items(template, benches)
        return run(self.offline, [east]), run(self.offline, [west])

    def assert_only_original_report(self, original):
        self.reopen_offline()
        self.assertEqual(read(self.offline, original.snapshot.report_id), original)
        with self.assertRaises(KeyError):
            read(self.offline, original.snapshot.report_id + 1)
        self.assertEqual(self.offline.execute('SELECT report_id FROM report_snapshot').fetchall(),
                         [(original.snapshot.report_id,)])
        self.assertEqual(self.offline.execute('SELECT report_id, ordinal FROM report_rows').fetchall(),
                         [(original.snapshot.report_id, 1)])
        self.assertEqual(self.offline.execute('SELECT request_id FROM report_first_receipt').fetchall(),
                         [(original.first_receipt.request_id,)])

    def test_publish_failure(self):
        old, new = self.old_and_new_results()
        first = publish(self.offline, 'old', old)
        original = read(self.offline, first.report_id)
        self.offline.executescript('''
            CREATE TABLE fixture_parent (id INTEGER PRIMARY KEY);
            CREATE TABLE fixture_deferred (
                id INTEGER REFERENCES fixture_parent(id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fixture_commit_failure AFTER INSERT ON report_first_receipt
            WHEN NEW.request_id = 'blocked-commit'
            BEGIN
                INSERT INTO fixture_deferred VALUES (99);
            END;
        ''')
        with self.assertRaises(PublishError) as error:
            publish(self.offline, 'blocked-commit', new)
        self.assertIsInstance(error.exception.__cause__, sqlite3.IntegrityError)
        self.assertEqual(error.exception.__cause__.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
        self.assertFalse(self.offline.in_transaction)
        self.assert_only_original_report(original)
        self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM fixture_deferred').fetchone()[0], 0)
        later = publish(self.offline, 'later', new)
        self.assertEqual(read(self.offline, later.report_id).snapshot.total, 13)

    def test_failure_after_rows(self):
        old, new = self.old_and_new_results()
        first = publish(self.offline, 'old', old)
        original = read(self.offline, first.report_id)
        self.offline.execute('''
            CREATE TRIGGER fixture_receipt_failure BEFORE INSERT ON report_first_receipt
            WHEN NEW.request_id = 'blocked-receipt' AND EXISTS (
                SELECT 1 FROM report_rows WHERE report_id = NEW.report_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'receipt blocked after row write');
            END
        ''')
        with self.assertRaises(PublishError) as error:
            publish(self.offline, 'blocked-receipt', new)
        self.assertIn('receipt blocked after row write', str(error.exception.__cause__))
        self.assert_only_original_report(original)

    def test_read_previous_report_after_reissue(self):
        author_path = self.folder / 'author.sqlite'
        source = load_sample('source.json')
        draft = build_draft('coat', source['template']['rows'])
        with closing(sqlite3.connect(author_path)) as author:
            initialize_source(author, source['batches'])
            freeze_template(author, draft, '1')
            freeze_bench(author, 'east', '1', [
                {'path': 'shift/east/zero', 'state': 'value', 'value': 3, 'source': 'old-log:1'},
            ])
            old_template = issue_template(author, 'coat', '1')
            old_bench = issue_bench(author, 'east', '1')
        template_id = receive(self.offline, old_template.packet)
        bench_id = receive(self.offline, old_bench.packet)
        old_receipt = publish(self.offline, 'old', run(self.offline, [ApplicationItem(template_id, bench_id, EAST_MOUNT)]))
        before = read(self.offline, old_receipt.report_id)
        draft.replace_rows([{**source['template']['rows'][0], 'reference': '../recalibrated'}])
        with closing(sqlite3.connect(author_path)) as author:
            freeze_template(author, draft, '2')
            freeze_bench(author, 'east', '2', [
                {'path': 'shift/east/recalibrated', 'state': 'value', 'value': 7, 'source': 'new-log:5'},
            ])
            new_template = issue_template(author, 'coat', '2')
            new_bench = issue_bench(author, 'east', '2')
            self.assertEqual(issue_template(author, 'coat', '1').packet, old_template.packet)
            self.assertEqual(issue_bench(author, 'east', '1').packet, old_bench.packet)
        author_path.unlink()
        self.assertNotEqual(new_template.number, old_template.number)
        self.assertNotEqual(new_bench.number, old_bench.number)
        new_template_id = receive(self.offline, new_template.packet)
        new_bench_id = receive(self.offline, new_bench.packet)
        self.assertNotEqual(new_template_id, template_id)
        self.assertNotEqual(new_bench_id, bench_id)
        current = run(self.offline, [ApplicationItem(new_template_id, new_bench_id, EAST_MOUNT)])
        new_receipt = publish(self.offline, 'new', current)
        self.reopen_offline()
        new_report = read(self.offline, new_receipt.report_id)
        old_report = read(self.offline, old_receipt.report_id)
        self.assertEqual(old_report, before)
        actual = [
            [report.snapshot.rows[0].raw_strength, report.snapshot.rows[0].strength,
             report.snapshot.rows[0].zero.value, report.snapshot.rows[0].zero.bench_evidence.source,
             report.snapshot.rows[0].source.locator, report.snapshot.total, report.first_receipt.request_id]
            for report in (old_report, new_report)
        ]
        expected = [[20, 17, 3, 'old-log:1', 'coat-a.csv:2', 17, 'old'],
                    [20, 13, 7, 'new-log:5', 'coat-a.csv:2', 13, 'new']]
        self.assertEqual(actual, expected)
        self.assertEqual((old_report.first_receipt, new_report.first_receipt), (old_receipt, new_receipt))
        self.assertEqual([(r.snapshot.rows[0].template_revision, r.snapshot.rows[0].bench_revision)
                          for r in (old_report, new_report)], [('1', '1'), ('2', '2')])
        emit_scenario(
            'v9.independent_snapshots', {'raw': 20, 'old_zero': 3, 'new_zero': 7, 'read_order': ['new', 'old']},
            [17, 13], [before.snapshot.rows[0].strength, current.rows[0].strength], expected, actual,
            ['template/issue.py', 'bench/issue.py', 'report/snapshots.py', 'report/readback.py'],
            'Each number must retain its signed 20 minus that revision’s zero and its original first receipt.',
        )

    def test_unknown_report(self):
        with self.assertRaisesRegex(KeyError, 'unknown report'):
            read(self.offline, 1)
        old, _ = self.old_and_new_results()
        receipt = publish(self.offline, 'exists', old)
        with self.assertRaisesRegex(KeyError, 'unknown report'):
            read(self.offline, receipt.report_id + 1)

    def test_same_request_retry(self):
        old, new = self.old_and_new_results()
        receipt = publish(self.offline, 'retry', old)
        self.reopen_offline()
        self.assertEqual(publish(self.offline, 'retry', old), receipt)
        with self.assertRaisesRegex(ValueError, 'different result'):
            publish(self.offline, 'retry', new)
        self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM report_snapshot').fetchone()[0], 1)
        original = read(self.offline, receipt.report_id)
        self.assertEqual(original.snapshot.rows, old.rows)
        self.assertEqual(original.first_receipt, receipt)
