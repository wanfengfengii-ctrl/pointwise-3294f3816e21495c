import json
import sqlite3
import unittest
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from bench.issue import issue_bench
from bench.revision import freeze_bench
from demo import load_sample
from disclosure_fixture import (
    ORDINALS, approval, issuance_anchors, prepare, sign,
)
from processing.applications import ApplicationItem
from processing.apply import run, verify_disclosure
from processing.envelopes import encode_envelope
from processing.intake import get_received, receive
from report.publish import publish
from report.readback import disclose, read
from source.initialize import initialize_source
from source.ingest import ingest
from template.draft import build_draft
from template.issue import decode_template_body, issue_template
from template.revision import freeze_template


def v2_template(db, name, revision):
    return issue_template(db, name, revision, version=2)


def v2_bench(db, bench, revision):
    return issue_bench(db, bench, revision, version=2)


class DisclosureCase(unittest.TestCase):
    """Build V2 artifacts in a throw-away author database, sign offline."""

    def setUp(self):
        self.folder = Path(self.enterContext(TemporaryDirectory(prefix='spectral-disclosure-test-')))
        self.author_path = self.folder / 'author.sqlite'
        self.handoff_path = self.folder / 'handoff.sqlite'
        with closing(sqlite3.connect(self.author_path)) as author:
            self.template, self.benches = prepare(author, v2_template, v2_bench)
        self.anchors = issuance_anchors(self.template, self.benches)
        with closing(sqlite3.connect(self.handoff_path)) as handoff:
            self.receipt = sign(handoff, self.template, self.benches)
        self.author_path.unlink()

    def open_handoff(self):
        return self.enterContext(closing(sqlite3.connect(self.handoff_path)))

    def sample_packet(self, ordinals=ORDINALS, db=None):
        if db is None:
            with closing(sqlite3.connect(self.handoff_path)) as connection:
                return disclose(connection, self.receipt.report_id, ordinals)
        return disclose(db, self.receipt.report_id, ordinals)

    def sample_roster(self):
        return approval(self.receipt.report_id, self.template, self.benches)

    def review(self, packet, roster=None):
        return verify_disclosure(self.anchors, roster if roster is not None else self.sample_roster(),
                                 json.loads(packet) if isinstance(packet, bytes) else packet)

    def assert_rejected(self, packet, roster=None):
        with self.assertRaises(ValueError):
            self.review(packet, roster)

    # ------------------------------------------------------------------
    # V2 issuance
    # ------------------------------------------------------------------

    def test_v2_envelope_anchor_is_stable(self):
        self.assertEqual(self.template.version, 2)
        digest = self.template.digest
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(character in '0123456789abcdef' for character in digest))
        # Re-issuing the same revision at the same version returns the original,
        # and the frozen bodies are identical across versions; only the anchor
        # organisation differs.
        with closing(sqlite3.connect(self.author_path)) as author:
            source = load_sample('source.json')
            initialize_source(author, source['batches'])
            draft = build_draft('coat', [source['template']['rows'][0],
                                         {**source['template']['rows'][0], 'measurement_id': 'M2'}])
            freeze_template(author, draft, '1')
            again = issue_template(author, 'coat', '1', version=2)
            self.assertEqual(again.packet, self.template.packet)
        original = json.loads(self.template.packet)
        self.assertEqual(original['version'], 2)
        self.assertEqual(original['digest'], digest)
        # The same frozen body under the V1 convention carries a different digest
        # (SHA-256 of the header) than the V2 issuance anchor.
        v1 = json.loads(encode_envelope('template', self.template.number, original['body'], version=1))
        self.assertEqual(original['body'], v1['body'])
        self.assertNotEqual(original['digest'], v1['digest'])
        self.assertEqual(decode_template_body(original['body']), decode_template_body(v1['body']))

    def test_version_switch_is_refused(self):
        author_path = self.folder / 'switch.sqlite'
        source = load_sample('source.json')
        with closing(sqlite3.connect(author_path)) as author:
            initialize_source(author, source['batches'])
            draft = build_draft('coat', source['template']['rows'])
            freeze_template(author, draft, '1')
            self.assertEqual(issue_template(author, 'coat', '1', version=1).version, 1)
            with self.assertRaisesRegex(ValueError, 'already fixed at version 1'):
                issue_template(author, 'coat', '1', version=2)
            freeze_template(author, draft, '2')
            self.assertEqual(issue_template(author, 'coat', '2', version=2).version, 2)
            with self.assertRaisesRegex(ValueError, 'already fixed at version 2'):
                issue_template(author, 'coat', '2', version=1)

    def test_v2_bench_issue_and_intake_redelivery(self):
        bench = self.benches[0]
        self.assertEqual(bench.version, 2)
        self.assertEqual(len(bench.digest), 64)
        handoff = self.open_handoff()
        first = receive(handoff, bench.packet)
        self.assertEqual(receive(handoff, bench.packet), first)
        repacked = json.dumps(json.loads(bench.packet), indent=2).encode('utf-8')
        self.assertEqual(receive(handoff, repacked), first)
        self.assertEqual(get_received(handoff, first).envelope.version, 2)

    def test_v2_run_publish_and_read(self):
        handoff = self.open_handoff()
        template_id = receive(handoff, self.template.packet)
        bench_id = receive(handoff, self.benches[0].packet)
        result = run(handoff, [ApplicationItem(template_id, bench_id, 'shift/east/read')])
        self.assertEqual([(row.strength, row.zero.bench_evidence.source) for row in result.rows],
                         [(17, 'east-log:8'), (17, 'east-log:8')])
        receipt = publish(handoff, 'v2-run', result)
        self.assertEqual(read(handoff, receipt.report_id).snapshot.total, 34)

    # ------------------------------------------------------------------
    # Limited disclosure: export
    # ------------------------------------------------------------------

    def test_disclose_selected_rows(self):
        packet = json.loads(self.sample_packet())
        self.assertEqual(packet['report_id'], self.receipt.report_id)
        self.assertEqual([row['ordinal'] for row in packet['rows']], list(ORDINALS))
        self.assertEqual([row['template_row'] for row in packet['rows']], [1, 1, 1])
        self.assertEqual([row['template_number'] for row in packet['rows']],
                         [self.template.number] * 3)
        self.assertEqual([row['bench_number'] for row in packet['rows']],
                         [self.benches[0].number, self.benches[1].number, self.benches[2].number])
        self.assertEqual([row['mount'] for row in packet['rows']],
                         ['shift/east/read', 'shift/west/read', 'shift/west/read'])
        self.assertEqual([row['entry']['state'] if row['entry'] else None for row in packet['rows']],
                         ['value', 'disabled', None])

    def test_disclosure_carries_no_other_rows_or_entries(self):
        raw = self.sample_packet().decode('utf-8')
        self.assertNotIn('M2', raw)
        self.assertNotIn('maintenance:', raw)
        self.assertNotIn('shift/check/zero', raw)
        records = json.loads(raw)['rows']
        seen = [row['entry']['path'] for row in records if row['entry'] is not None]
        self.assertEqual(seen, ['shift/east/zero', 'shift/west/zero'])
        keys = {key for row in records for key in row['bench_proof']}
        self.assertEqual(keys, {'path', 'siblings'})
        # The template payload only carries the approved original, not M2.
        self.assertEqual({row['template']['source']['measurement_id'] for row in records}, {'M1'})

    def test_disclose_requires_v2_rows(self):
        source = load_sample('source.json')
        v1_path = self.folder / 'v1.sqlite'
        with closing(sqlite3.connect(v1_path)) as author:
            template, benches = prepare(author)
            receipt = sign(author, template, benches)
        with closing(sqlite3.connect(v1_path)) as connection:
            with self.assertRaisesRegex(ValueError, 'version 1'):
                disclose(connection, receipt.report_id, (1,))
        # The old interface still reads the whole V1 report.
        with closing(sqlite3.connect(v1_path)) as connection:
            self.assertEqual(len(read(connection, receipt.report_id).snapshot.rows), 6)

    def test_disclose_ordinal_validation(self):
        handoff = self.open_handoff()
        for ordinals in ((), [], (0,), (7,), (1, 1), (1, True), ('1',)):
            with self.subTest(ordinals=ordinals):
                with self.assertRaises(ValueError):
                    disclose(handoff, self.receipt.report_id, ordinals)
        with self.assertRaises(KeyError):
            disclose(handoff, 9999, (1,))

    def test_disclose_output_order_follows_input(self):
        packet = json.loads(self.sample_packet((5, 3, 1)))
        self.assertEqual([row['ordinal'] for row in packet['rows']], [5, 3, 1])
        roster = self.sample_roster()
        roster['rows'] = [roster['rows'][2], roster['rows'][1], roster['rows'][0]]
        reviewed = self.review(packet, roster)
        self.assertEqual([row['ordinal'] for row in reviewed['rows']], [5, 3, 1])
        self.assertEqual([row['strength'] for row in reviewed['rows']], [18, None, 17])
        self.assertEqual(reviewed['total'], 35)

    # ------------------------------------------------------------------
    # Database-free review
    # ------------------------------------------------------------------

    def test_review_recomputes_approved_rows(self):
        reviewed = self.review(self.sample_packet())
        self.assertEqual(reviewed['report_id'], self.receipt.report_id)
        self.assertEqual([row['ordinal'] for row in reviewed['rows']], [1, 3, 5])
        self.assertEqual([row['strength'] for row in reviewed['rows']], [17, None, 18])
        self.assertEqual(reviewed['total'], 35)
        zeroes = [row['zero'] for row in reviewed['rows']]
        self.assertEqual([zero['kind'] for zero in zeroes], ['bench', 'disabled', 'default'])
        self.assertEqual(zeroes[0]['value'], 3)
        self.assertEqual(zeroes[1]['bench_evidence']['source'], 'west-lockout:12')
        self.assertEqual(zeroes[2]['default_source'], 'worksheet/coat:B4')
        self.assertEqual(reviewed['rows'][0]['source'],
                         asdict(decode_template_body(self.template.body).rows[0].source))
        # Row ordinals 5 (default) recompute from the same original observation.
        self.assertEqual({row['raw_strength'] for row in reviewed['rows']}, {20})

    def test_review_accepts_raw_packet_bytes(self):
        reviewed = self.review(self.sample_packet())
        self.assertEqual(reviewed['total'], 35)

    def test_review_rejects_duplicate_json_fields(self):
        raw = self.sample_packet().decode('utf-8')
        tampered = raw.replace('"report_id":', '"report_id":1,"report_id":', 1)
        with self.assertRaises(ValueError):
            verify_disclosure(self.anchors, self.sample_roster(), tampered.encode('utf-8'))

    def test_review_benches_may_differ_per_row(self):
        # Same original fact (M1/20) is reviewed under three different benches.
        packet = json.loads(self.sample_packet())
        identities = {row['bench_number'] for row in packet['rows']}
        self.assertEqual(len(identities), 3)

    def test_missing_entry_default_is_legitimate(self):
        # Row 5 targets a genuinely absent path: entry is null and the default applies.
        packet = json.loads(self.sample_packet())
        missing = packet['rows'][2]
        self.assertIsNone(missing['entry'])
        self.assertEqual(self.review(packet)['rows'][2]['zero']['kind'], 'default')

    def test_mixed_version_report_cannot_be_disclosed(self):
        # A V2 bench with a V1 template: the report stays readable, but the
        # selected row references a V1 issue so export is refused.
        source = load_sample('source.json')
        path = self.folder / 'mixed.sqlite'
        with closing(sqlite3.connect(path)) as db:
            initialize_source(db, source['batches'])
            freeze_template(db, build_draft('coat', [source['template']['rows'][0]]), '1')
            freeze_bench(db, 'east', '1', load_sample('benches.json')[0]['entries'])
            template = issue_template(db, 'coat', '1')
            bench = issue_bench(db, 'east', '1', version=2)
            receipt = publish(db, 'mixed', run(db, [
                ApplicationItem(receive(db, template.packet), receive(db, bench.packet),
                                'shift/east/read')
            ]))
            with self.assertRaisesRegex(ValueError, 'version 1 template'):
                disclose(db, receipt.report_id, (1,))
            self.assertEqual(read(db, receipt.report_id).snapshot.total, 17)

    def test_disclose_after_other_revision_reexport(self):
        # A second template revision issued V2 gets its own number/anchor and
        # the first report still exports against the first template number.
        source = load_sample('source.json')
        path = self.folder / 'two-revisions.sqlite'
        rule = source['template']['rows'][0]
        with closing(sqlite3.connect(path)) as db:
            initialize_source(db, source['batches'])
            freeze_bench(db, 'east', '1', load_sample('benches.json')[0]['entries'])
            bench = issue_bench(db, 'east', '1', version=2)
            bench_id = receive(db, bench.packet)
            first_draft = build_draft('coat', [rule])
            freeze_template(db, first_draft, '1')
            first = issue_template(db, 'coat', '1', version=2)
            first_report = publish(db, 'first', run(db, [
                ApplicationItem(receive(db, first.packet), bench_id, 'shift/east/read')]))
            first_draft.replace_rows([{**rule, 'reference': '../check/zero'}])
            freeze_template(db, first_draft, '2')
            second = issue_template(db, 'coat', '2', version=2)
            second_report = publish(db, 'second', run(db, [
                ApplicationItem(receive(db, second.packet), bench_id, 'shift/east/read')]))
            self.assertNotEqual(first.number, second.number)
            self.assertNotEqual(first.digest, second.digest)
            packet = json.loads(disclose(db, first_report.report_id, (1,)))
            self.assertEqual(packet['rows'][0]['template_number'], first.number)
            anchors = {(first.kind, first.number): first.digest, (bench.kind, bench.number): bench.digest}
            roster = {'report_id': first_report.report_id, 'rows': [
                {'ordinal': 1, 'template_number': first.number, 'template_row': 1,
                 'bench_number': bench.number, 'mount': 'shift/east/read'}]}
            self.assertEqual(verify_disclosure(anchors, roster, packet)['rows'][0]['strength'], 17)
            # The other report references the second template; its own export is valid.
            second_packet = json.loads(disclose(db, second_report.report_id, (1,)))
            self.assertEqual(second_packet['rows'][0]['template_number'], second.number)

    def test_missing_entry_without_default(self):
        author_path = self.folder / 'no-default.sqlite'
        source = load_sample('source.json')
        rule = dict(source['template']['rows'][0])
        del rule['default']
        with closing(sqlite3.connect(author_path)) as author:
            initialize_source(author, source['batches'])
            freeze_template(author, build_draft('coat', [rule]), '1')
            template = issue_template(author, 'coat', '1', version=2)
            freeze_bench(author, 'west', 'missing', [])
            bench = issue_bench(author, 'west', 'missing', version=2)
            anchors = {(template.kind, template.number): template.digest,
                       (bench.kind, bench.number): bench.digest}
            receipt = publish(author, 'no-default', run(author, [
                ApplicationItem(receive(author, template.packet), receive(author, bench.packet),
                                'shift/west/read')
            ]))
            packet = json.loads(disclose(author, receipt.report_id, (1,)))
            reviewed = verify_disclosure(anchors, {
                'report_id': receipt.report_id,
                'rows': [{'ordinal': 1, 'template_number': template.number, 'template_row': 1,
                          'bench_number': bench.number, 'mount': 'shift/west/read'}],
            }, packet)
        row = reviewed['rows'][0]
        self.assertIsNone(row['strength'])
        self.assertEqual(row['zero']['kind'], 'missing')
        self.assertEqual(row['zero']['path'], 'shift/west/zero')
        self.assertIsNone(row['zero']['value'])
        self.assertEqual(reviewed['total'], 0)

    def test_entry_null_for_present_path_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'][0]['entry'] = None
        self.assert_rejected(packet)

    def test_dropped_lockout_evidence_rejected(self):
        packet = json.loads(self.sample_packet())
        retired = packet['rows'][1]
        retired['entry'] = None
        retired['bench_proof'] = packet['rows'][2]['bench_proof']
        self.assert_rejected(packet)

    def test_substituted_original_rejected(self):
        # Two same-value originals (M1 and M2, both 20) must not be swapped.
        source = load_sample('source.json')
        row = source['template']['rows'][0]
        author_path = self.folder / 'swap.sqlite'
        with closing(sqlite3.connect(author_path)) as author:
            initialize_source(author, source['batches'])
            draft = build_draft('coat', [row, {**row, 'measurement_id': 'M2'}])
            freeze_template(author, draft, '1')
            template = issue_template(author, 'coat', '1', version=2)
            freeze_bench(author, 'east', '1', load_sample('benches.json')[0]['entries'])
            bench = issue_bench(author, 'east', '1', version=2)
            anchors = {(template.kind, template.number): template.digest,
                       (bench.kind, bench.number): bench.digest}
            receipt = publish(author, 'swap', run(author, [
                ApplicationItem(receive(author, template.packet), receive(author, bench.packet), 'shift/east/read')
            ]))
            packet = disclose(author, receipt.report_id, (1,))
            roster = {'report_id': receipt.report_id, 'rows': [
                {'ordinal': 1, 'template_number': template.number, 'template_row': 1,
                 'bench_number': bench.number, 'mount': 'shift/east/read'},
            ]}
            reviewed = verify_disclosure(anchors, roster, json.loads(packet))
            self.assertEqual(reviewed['rows'][0]['source']['measurement_id'], 'M1')
            swapped = json.loads(packet)
            swapped['rows'][0]['template'], other = (
                decode_template_body(template.body).rows[1].to_record(), None)
            with self.assertRaises(ValueError):
                verify_disclosure(anchors, roster, swapped)
            # The M2 packet bytes never travel in the approved export.
            self.assertNotIn('M2', packet.decode('utf-8'))

    def test_wrong_row_position_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'][0]['template_row'] = 2
        self.assert_rejected(packet)
        packet = json.loads(self.sample_packet())
        packet['rows'][0]['template_proof']['index'] = 2
        self.assert_rejected(packet)

    def test_wrong_bench_proof_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'][0]['bench_proof'] = packet['rows'][1]['bench_proof']
        self.assert_rejected(packet)

    def test_absent_proof_from_another_revision_rejected(self):
        # Row 5 uses the "missing" west revision.  Swap in a proof from a
        # different revision of the same bench, where the path does exist.
        packet = json.loads(self.sample_packet())
        retired = packet['rows'][1]
        retired['entry'] = None
        retired['bench_proof'] = packet['rows'][2]['bench_proof']
        self.assert_rejected(packet)

    def test_entry_for_other_path_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'][0]['entry']['path'] = 'shift/west/zero'
        self.assert_rejected(packet)

    def test_entry_value_tamper_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'][0]['entry']['value'] = format(5, 'x')
        self.assert_rejected(packet)

    def test_bench_proof_target_mismatch_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'][0]['bench_proof']['path'] = 'shift/west/zero'
        self.assert_rejected(packet)

    def test_wrong_anchor_rejected(self):
        packet = self.sample_packet()
        anchors = dict(self.anchors)
        key = ('template', self.template.number)
        anchors[key] = '0' * 64
        with self.assertRaises(ValueError):
            verify_disclosure(anchors, self.sample_roster(), json.loads(packet))

    def test_missing_anchor_rejected(self):
        with self.assertRaises(ValueError):
            verify_disclosure({}, self.sample_roster(), json.loads(self.sample_packet()))

    def test_missing_proof_rejected(self):
        for field in ('template_proof', 'bench_proof'):
            with self.subTest(field=field):
                packet = json.loads(self.sample_packet())
                del packet['rows'][1][field]
                self.assert_rejected(packet)

    def test_extra_row_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'].append(dict(packet['rows'][0]))
        self.assert_rejected(packet)

    def test_reordered_rows_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'][0], packet['rows'][1] = packet['rows'][1], packet['rows'][0]
        self.assert_rejected(packet)

    def test_roster_validation(self):
        packet = self.sample_packet()
        base = self.sample_roster()
        for mutate in (
            lambda roster: roster.update(report_id=roster['report_id'] + 1),
            lambda roster: roster['rows'].pop(),
            lambda roster: roster['rows'].append(dict(roster['rows'][-1], ordinal=7)),
            lambda roster: roster['rows'][0].update(ordinal=3),
            lambda roster: roster['rows'][0].update(mount='shift/./east/read'),
            lambda roster: roster['rows'][0].update(template_row=2),
        ):
            with self.subTest(mutate=mutate):
                roster = json.loads(json.dumps(base))
                mutate(roster)
                self.assert_rejected(packet, roster)

    def test_duplicate_roster_ordinal_rejected(self):
        roster = self.sample_roster()
        roster['rows'][1]['ordinal'] = 1
        self.assert_rejected(self.sample_packet(), roster)

    def test_conflicting_template_reading_rejected(self):
        packet = json.loads(self.sample_packet())
        packet['rows'][0]['template']['raw_strength'] = format(21, 'x')
        self.assert_rejected(packet)

    def test_multi_row_template_proofs(self):
        # Three template rows exercise non-power-of-two Merkle proofs.
        author_path = self.folder / 'three.sqlite'
        source = load_sample('source.json')
        rule = source['template']['rows'][0]
        with closing(sqlite3.connect(author_path)) as author:
            initialize_source(author, source['batches'])
            ingest(author, 'extra', [{'measurement_id': 'M3', 'strength': 25, 'source': 'coat-a.csv:4'}])
            draft = build_draft('coat', [
                rule,
                {**rule, 'measurement_id': 'M2', 'reference': '../zero'},
                {'batch_id': 'extra', 'measurement_id': 'M3', 'reference': '../zero',
                 'reference_source': 'worksheet/coat:A5', 'default': rule['default']},
            ])
            freeze_template(author, draft, '1')
            template = issue_template(author, 'coat', '1', version=2)
            freeze_bench(author, 'east', '1', load_sample('benches.json')[0]['entries'])
            bench = issue_bench(author, 'east', '1', version=2)
            anchors = {(template.kind, template.number): template.digest,
                       (bench.kind, bench.number): bench.digest}
            template_id = receive(author, template.packet)
            bench_id = receive(author, bench.packet)
            receipt = publish(author, 'three', run(author, [
                ApplicationItem(template_id, bench_id, 'shift/east/read')]))
            reviewed = verify_disclosure(anchors, {
                'report_id': receipt.report_id,
                'rows': [
                    {'ordinal': ordinal, 'template_number': template.number, 'template_row': row,
                     'bench_number': bench.number, 'mount': 'shift/east/read'}
                    for ordinal, row in ((1, 1), (2, 2), (3, 3))
                ],
            }, json.loads(disclose(author, receipt.report_id, (1, 2, 3))))
        self.assertEqual([row['source']['measurement_id'] for row in reviewed['rows']], ['M1', 'M2', 'M3'])
        self.assertEqual([row['strength'] for row in reviewed['rows']], [17, 17, 22])
        self.assertEqual(reviewed['total'], 56)

    def test_verify_signature_has_no_database(self):
        import inspect
        parameters = list(inspect.signature(verify_disclosure).parameters)
        self.assertEqual(parameters, ['anchors', 'roster', 'packet'])

    def test_disclosure_after_author_database_closed(self):
        # The authoring database is gone; only the signed offline store remains.
        self.assertFalse(self.author_path.exists())
        with closing(sqlite3.connect(self.handoff_path)) as handoff:
            packet = disclose(handoff, self.receipt.report_id, ORDINALS)
        self.assertEqual(self.review(packet)['total'], 35)


class DisclosureOrderingTests(DisclosureCase):
    def test_roster_order_drives_review_and_subtotals(self):
        # The approved list may order rows differently; the packet must agree.
        packet = json.loads(self.sample_packet((1, 3, 5)))
        roster = self.sample_roster()
        roster['rows'] = [roster['rows'][2], roster['rows'][0], roster['rows'][1]]
        self.assert_rejected(packet, roster)
        packet = json.loads(self.sample_packet((5, 1, 3)))
        reviewed = self.review(packet, roster)
        self.assertEqual([row['ordinal'] for row in reviewed['rows']], [5, 1, 3])
        self.assertEqual([row['strength'] for row in reviewed['rows']], [18, 17, None])
        self.assertEqual(reviewed['total'], 35)
