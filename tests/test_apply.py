import json
import sqlite3
from contextlib import closing

from bench.issue import issue_bench
from bench.revision import freeze_bench
from processing.applications import ApplicationItem
from processing.apply import run
from processing.envelopes import encode_envelope, issue_number
from processing.intake import get_received, receive
from report.publish import publish
from report.readback import read
from source.ingest import ingest
from storage import has_table
from template.draft import build_draft
from template.issue import issue_template
from template.revision import freeze_template
from tests.helpers import EAST_MOUNT, WEST_MOUNT, OfflineCase, emit_scenario


class ApplyTests(OfflineCase):
    def test_bad_envelope(self):
        template, benches = self.packets()
        original = benches['east', '1']
        tampered = json.loads(original.packet)
        tampered['body']['entries'][0]['source'] = 'altered'
        wrong_identity = encode_envelope('bench', issue_number('wrong', '1'), original.body)
        invalid_body = {**original.body, 'entries': [
            {'path': 'zero', 'state': 'value', 'value': None, 'source': 'bad:1'},
        ]}
        for packet in (original.packet[:-1], json.dumps(tampered).encode(), wrong_identity,
                       encode_envelope('bench', original.number, invalid_body)):
            with self.subTest(packet=packet):
                with self.assertRaises(ValueError):
                    receive(self.offline, packet)
        self.assertFalse(has_table(self.offline, 'received_package'))
        template_id = receive(self.offline, template.packet)
        bench_id = receive(self.offline, original.packet)
        self.assertEqual(run(self.offline, [ApplicationItem(template_id, bench_id, EAST_MOUNT)]).rows[0].strength, 17)

    def test_redelivery(self):
        template, benches = self.packets()
        for package in (template, benches['east', '1']):
            receipt_id = receive(self.offline, package.packet)
            self.assertEqual(receive(self.offline, package.packet), receipt_id)
            repacked = json.dumps(json.loads(package.packet), indent=2).encode('utf-8')
            self.assertEqual(receive(self.offline, repacked), receipt_id)
            self.assertEqual(get_received(self.offline, receipt_id).envelope.packet, package.packet)
        self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM received_package').fetchone()[0], 2)

    def test_same_number_conflict(self):
        template, benches = self.packets()
        original = benches['east', '1']
        alternative = {**original.body, 'entries': [
            {'path': 'shift/east/zero', 'state': 'value', 'value': '7', 'source': 'alternate-log:1'},
        ]}
        conflict = encode_envelope('bench', original.number, alternative)
        template_id = receive(self.offline, template.packet)
        bench_id = receive(self.offline, original.packet)
        with self.assertRaisesRegex(ValueError, 'different content'):
            receive(self.offline, conflict)
        self.assertEqual(get_received(self.offline, bench_id).envelope.packet, original.packet)
        row, = run(self.offline, [ApplicationItem(template_id, bench_id, EAST_MOUNT)]).rows
        self.assertEqual((row.strength, row.zero.bench_evidence.source), (17, 'east-log:8'))
        self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM received_package').fetchone()[0], 2)

    def test_same_template_two_benches(self):
        template, benches = self.receive_inputs()
        items = self.two_bench_items(template, benches)
        result = run(self.offline, items)
        actual = [
            [row.application_index, row.source.measurement_id, row.strength, row.zero.value, row.zero.path,
             row.zero.bench_evidence.bench, row.zero.bench_evidence.source]
            for row in result.rows
        ]
        expected = [
            [1, 'M1', 17, 3, 'shift/east/zero', 'east', 'east-log:8'],
            [2, 'M1', 13, 7, 'shift/west/zero', 'west', 'west-log:5'],
        ]
        self.assertEqual(actual, expected)
        self.assertEqual([row.template_receipt for row in result.rows], [template, template])
        self.assertEqual([row.source.locator for row in result.rows], ['coat-a.csv:2', 'coat-a.csv:2'])
        receipt = publish(self.offline, 'two-benches', result)
        stored = read(self.offline, receipt.report_id)
        self.assertEqual(stored.snapshot.rows, result.rows)
        self.assertEqual(stored.snapshot.total, 30)
        self.assertEqual(stored.first_receipt, receipt)
        emit_scenario(
            'v5', {'raw': 20, 'reference': '../zero', 'mounts': [EAST_MOUNT, WEST_MOUNT], 'zeros': [3, 7]},
            expected, actual, {'total': 30, 'request': 'two-benches'},
            {'total': stored.snapshot.total, 'request': stored.first_receipt.request_id},
            ['processing/applications.py', 'processing/apply.py', 'report/publish.py', 'report/readback.py'],
            'One parent step locates the zero at each mount. Subtract 3 and 7 from 20 and sum 17 plus 13.',
        )

    def test_same_bench_two_mounts(self):
        template, benches = self.receive_inputs()
        east = benches['east', '1']
        rows = run(self.offline, [
            ApplicationItem(template, east, EAST_MOUNT),
            ApplicationItem(template, east, 'shift/check/read'),
        ]).rows
        self.assertEqual([(row.strength, row.zero.path, row.zero.bench_evidence.source) for row in rows],
                         [(17, 'shift/east/zero', 'east-log:8'), (9, 'shift/check/zero', 'east-log:9')])

    def test_reversed_order(self):
        template, benches = self.receive_inputs()
        east, west = self.two_bench_items(template, benches)
        rows = run(self.offline, [west, east]).rows
        self.assertEqual([(row.application_index, row.bench, row.strength, row.zero.bench_evidence.source) for row in rows],
                         [(1, 'west', 13, 'west-log:5'), (2, 'east', 17, 'east-log:8')])

    def test_template_row_order_inside_each_application(self):
        with closing(sqlite3.connect(':memory:')) as author:
            ingest(author, 'scan', [
                {'measurement_id': 'first', 'strength': 20, 'source': 'scan:1'},
                {'measurement_id': 'second', 'strength': 30, 'source': 'scan:2'},
            ])
            draft = build_draft('ordered', [
                {'batch_id': 'scan', 'measurement_id': name, 'reference': '../zero'}
                for name in ['second', 'first']
            ])
            freeze_template(author, draft, '1')
            freeze_bench(author, 'east', '1', [
                {'path': 'shift/east/zero', 'state': 'value', 'value': 3, 'source': 'east:1'},
                {'path': 'shift/check/zero', 'state': 'value', 'value': 7, 'source': 'east:2'},
            ])
            template_packet = issue_template(author, 'ordered', '1').packet
            bench_packet = issue_bench(author, 'east', '1').packet
        template = receive(self.offline, template_packet)
        bench = receive(self.offline, bench_packet)
        rows = run(self.offline, [
            ApplicationItem(template, bench, EAST_MOUNT), ApplicationItem(template, bench, 'shift/check/read'),
        ]).rows
        self.assertEqual([(r.application_index, r.template_row, r.source.measurement_id, r.strength) for r in rows],
                         [(1, 1, 'second', 27), (1, 2, 'first', 17), (2, 1, 'second', 23), (2, 2, 'first', 13)])

    def test_disabled_missing_and_zero(self):
        template, benches = self.receive_inputs()
        no_default, _ = self.receive_inputs(default=False)
        items = [
            ApplicationItem(template, benches['west', 'disabled'], WEST_MOUNT),
            ApplicationItem(template, benches['west', 'missing'], WEST_MOUNT),
            ApplicationItem(no_default, benches['west', 'missing'], WEST_MOUNT),
            ApplicationItem(template, benches['west', 'zero'], WEST_MOUNT),
        ]
        disabled, fallback, missing, zero = run(self.offline, items).rows
        self.assertEqual([(row.strength, row.zero.kind, row.zero.value) for row in (disabled, fallback, missing, zero)],
                         [(None, 'disabled', None), (18, 'default', 2), (None, 'missing', None), (20, 'bench', 0)])
        self.assertEqual(disabled.zero.bench_evidence.source, 'west-lockout:12')
        self.assertIsNone(disabled.zero.default_source)
        self.assertEqual(fallback.zero.default_source, 'worksheet/coat:B4')
        self.assertIsNone(fallback.zero.bench_evidence)
        self.assertEqual(missing.zero.path, 'shift/west/zero')
        self.assertIsNone(missing.zero.bench_evidence)
        self.assertEqual(zero.zero.bench_evidence.source, 'west-log:13')
        self.assertEqual([r.source.measurement_id for r in (disabled, fallback, missing, zero)], ['M1'] * 4)

    def test_disabled_report_total(self):
        template, benches = self.receive_inputs()
        evidence = []
        for revision, readings, total in [('disabled', [17, None], 17), ('missing', [17, 18], 35)]:
            result = run(self.offline, self.two_bench_items(template, benches, revision))
            receipt = publish(self.offline, f'west-{revision}', result)
            stored = read(self.offline, receipt.report_id).snapshot
            self.assertEqual([row.strength for row in stored.rows], readings)
            self.assertEqual(stored.total, total)
            evidence.append({'rows': [row.strength for row in stored.rows], 'total': stored.total})
        disabled_only = run(self.offline, [ApplicationItem(template, benches['west', 'disabled'], WEST_MOUNT)])
        receipt = publish(self.offline, 'disabled-only', disabled_only)
        stored = read(self.offline, receipt.report_id).snapshot
        self.assertEqual((stored.total, len(stored.rows), stored.rows[0].zero.bench_evidence.source),
                         (0, 1, 'west-lockout:12'))
        expected = [{'rows': [17, None], 'total': 17}, {'rows': [17, 18], 'total': 35}]
        emit_scenario(
            'v6.disabled_report_total', {'raw': 20, 'east_zero': 3, 'default': 2, 'west_states': ['disabled', 'missing']},
            [None, 18], [item['rows'][1] for item in evidence], expected, evidence,
            ['template/calibration.py', 'processing/apply.py', 'report/totals.py', 'report/readback.py'],
            'A disabled line supplies no reading. An absent entry supplies the default 2, so west adds 18 only in the second report.',
        )

    def test_exact_integer_roundtrip(self):
        raw, zero = 1 << 20000, -(1 << 17000)
        with closing(sqlite3.connect(':memory:')) as author:
            ingest(author, 'big', [{'measurement_id': 'B', 'strength': raw, 'source': 'instrument:1'}])
            draft = build_draft('big', [{'batch_id': 'big', 'measurement_id': 'B', 'reference': 'zero'}])
            freeze_template(author, draft, '1')
            freeze_bench(author, 'big', '1', [
                {'path': 'zero', 'state': 'value', 'value': zero, 'source': 'bench:1'},
            ])
            template_packet = issue_template(author, 'big', '1').packet
            bench_packet = issue_bench(author, 'big', '1').packet
        template = receive(self.offline, template_packet)
        bench = receive(self.offline, bench_packet)
        receipt = publish(self.offline, 'exact', run(self.offline, [ApplicationItem(template, bench, '')] * 2))
        self.reopen_offline()
        stored = read(self.offline, receipt.report_id).snapshot
        expected = (1 << 20000) + (1 << 17000)
        self.assertEqual(stored.total, (1 << 20001) + (1 << 17001))
        self.assertEqual([(row.raw_strength, row.zero.value, row.strength) for row in stored.rows],
                         [(raw, zero, expected), (raw, zero, expected)])

    def test_escape_bench_root(self):
        template, benches = self.receive_inputs()
        first, _ = self.two_bench_items(template, benches)
        old = publish(self.offline, 'old', run(self.offline, [first]))
        for mount in ('', '../shift/east/read'):
            with self.subTest(mount=mount):
                with self.assertRaisesRegex(ValueError, 'leaves the bench root'):
                    publish(self.offline, 'escape', run(self.offline, [
                        first, ApplicationItem(template, benches['east', '1'], mount),
                    ]))
        self.assertEqual(self.offline.execute('SELECT request_id FROM report_first_receipt').fetchall(), [('old',)])
        self.assertEqual(self.offline.execute('SELECT report_id FROM report_snapshot').fetchall(), [(old.report_id,)])
        self.assertEqual(read(self.offline, old.report_id).snapshot.total, 17)

    def test_unknown_receipt(self):
        template, benches = self.receive_inputs()
        first, _ = self.two_bench_items(template, benches)
        with self.assertRaises(KeyError):
            publish(self.offline, 'missing-receipt', run(self.offline, [
                first, ApplicationItem(template, 9999, WEST_MOUNT),
            ]))
        with self.assertRaisesRegex(ValueError, 'expected bench'):
            run(self.offline, [ApplicationItem(template, template, EAST_MOUNT)])
        self.assertFalse(has_table(self.offline, 'report_snapshot'))
        self.assertFalse(has_table(self.offline, 'report_first_receipt'))

    def test_reference_cannot_leave_and_reenter_root(self):
        with closing(sqlite3.connect(':memory:')) as author:
            ingest(author, 'scan', [{'measurement_id': 'M', 'strength': 20, 'source': 'scan:1'}])
            draft = build_draft('coat', [{'batch_id': 'scan', 'measurement_id': 'M', 'reference': '../../shift/zero'}])
            freeze_template(author, draft, '1')
            freeze_bench(author, 'east', '1', [
                {'path': 'shift/zero', 'state': 'value', 'value': 3, 'source': 'east:1'},
            ])
            template = receive(self.offline, issue_template(author, 'coat', '1').packet)
            bench = receive(self.offline, issue_bench(author, 'east', '1').packet)
        with self.assertRaisesRegex(ValueError, 'leaves the bench root'):
            run(self.offline, [ApplicationItem(template, bench, 'read')])
