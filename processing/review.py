"""Database-free limited-row review of an already signed hand-off."""

from collections.abc import Mapping
from dataclasses import asdict

from bench.entries import BenchEntry, BenchEntryState
from bench.paths import normalize_entry_path, resolve_relative
from bench.sources import make_bench_evidence
from processing import proofs
from processing.envelopes import parse_issue_number
from storage import canonical_json, decode_integer, integer, parse_json, text
from template.calibration import ZeroDecision, decide_zero
from template.revision import FrozenTemplateRow

IDENTITY_FIELDS = ('ordinal', 'template_number', 'template_row', 'bench_number', 'mount')
ROW_FIELDS = (*IDENTITY_FIELDS, 'template', 'template_proof', 'bench_proof', 'entry')
TEMPLATE_PROOF_FIELDS = ('index', 'count', 'siblings')
BENCH_PROOF_FIELDS = ('path', 'siblings')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _positive(value, label):
    value = integer(value, label)
    _require(value > 0, f'{label} must be positive')
    return value


def _exact(record, fields, label):
    _require(isinstance(record, dict), f'{label} must be an object')
    _require(set(record) == set(fields), f'invalid fields for {label}')
    return record


def _roster(roster):
    _exact(roster, ('report_id', 'rows'), 'roster')
    report_id = _positive(roster['report_id'], 'roster report ID')
    rows = roster['rows']
    _require(isinstance(rows, (list, tuple)) and rows, 'roster rows must be a nonempty ordered sequence')
    identities = []
    seen = set()
    for record in rows:
        _exact(record, IDENTITY_FIELDS, 'roster row')
        ordinal = _positive(record['ordinal'], 'roster ordinal')
        _require(ordinal not in seen, 'roster ordinals must not repeat')
        seen.add(ordinal)
        mount = normalize_entry_path(record['mount'])
        _require(mount == record['mount'], 'roster mount must already be normalized')
        identities.append({
            'ordinal': ordinal,
            'template_number': text(record['template_number'], 'roster template number'),
            'template_row': _positive(record['template_row'], 'roster template row'),
            'bench_number': text(record['bench_number'], 'roster bench number'),
            'mount': mount,
        })
    return report_id, identities


def _packet(packet):
    if isinstance(packet, (bytes, bytearray, str)):
        try:
            raw = packet.encode('utf-8') if isinstance(packet, str) else bytes(packet)
            packet = parse_json(raw.decode('utf-8'))
        except (UnicodeError, RecursionError, ValueError) as exc:
            raise ValueError(f'invalid disclosure packet: {exc}') from exc
    _exact(packet, ('report_id', 'rows'), 'disclosure packet')
    report_id = _positive(packet['report_id'], 'disclosure report ID')
    _require(isinstance(packet['rows'], (list, tuple)), 'disclosure rows must be an ordered sequence')
    return report_id, packet['rows']


def _anchor(anchors, kind, number):
    _require(isinstance(anchors, Mapping), 'anchors must be keyed by (kind, number)')
    try:
        value = anchors[kind, number]
    except KeyError as exc:
        raise ValueError(f'no issuance anchor for {kind} issue {number!r}') from exc
    return proofs.from_hex(value, f'{kind} anchor')


def _hexes(values, label):
    _require(isinstance(values, (list, tuple)), f'{label} must be a sequence')
    return [proofs.from_hex(value, label) for value in values]


def _template_row(record):
    _exact(record, ('source', 'raw_strength', 'reference', 'reference_source', 'default'), 'disclosure template')
    row = FrozenTemplateRow.from_record(record)
    _require(canonical_json(row.to_record()) == canonical_json(record),
             'disclosure template row is not in canonical form')
    return row


def _bench_entry(record, number, target):
    if record is None:
        return None
    _exact(record, ('path', 'state', 'value', 'source'), 'disclosure entry')
    _require(record['path'] == target, 'disclosure entry path differs from the resolved path')
    bench, revision = parse_issue_number(number)
    try:
        state = BenchEntryState(record['state'])
    except ValueError as exc:
        raise ValueError('invalid disclosure entry state') from exc
    value = record['value']
    if state is BenchEntryState.VALUE:
        value = decode_integer(value)
    else:
        _require(value is None, 'disabled disclosure entry must have an empty value')
    entry = BenchEntry(target, state, value, make_bench_evidence(bench, revision, target, record['source']))
    _require(canonical_json(entry.to_record()) == canonical_json(record),
             'disclosure entry is not in canonical form')
    return entry


def _review_row(record, identity, anchors):
    _exact(record, ROW_FIELDS, 'disclosure row')
    for field in IDENTITY_FIELDS:
        _require(record[field] == identity[field], f'disclosure row {field} differs from the roster')

    template_number = identity['template_number']
    template_row = identity['template_row']
    target_path = identity['mount']

    template = _template_row(record['template'])
    template_anchor = _anchor(anchors, 'template', template_number)
    tproof = _exact(record['template_proof'], TEMPLATE_PROOF_FIELDS, 'template proof')
    _require(tproof['index'] == template_row, 'template proof index differs from the roster row')
    count = _positive(tproof['count'], 'template proof count')
    leaf = proofs.template_leaf(template_number, count, template_row, template.to_record())
    try:
        root = proofs.fold_template(leaf, _hexes(tproof['siblings'], 'template proof sibling'), template_row, count)
    except ValueError as exc:
        raise ValueError(f'invalid template proof: {exc}') from exc
    _require(root == template_anchor, 'template proof does not match the issuance anchor')

    target = resolve_relative(target_path, template.reference)
    bench_number = identity['bench_number']
    bench_anchor = _anchor(anchors, 'bench', bench_number)
    entry = _bench_entry(record['entry'], bench_number, target)
    bproof = _exact(record['bench_proof'], BENCH_PROOF_FIELDS, 'bench proof')
    _require(bproof['path'] == target, 'bench proof path differs from the resolved path')
    siblings = _hexes(bproof['siblings'], 'bench proof sibling')
    _require(len(siblings) == proofs.BENCH_DEPTH, 'bench proof must carry 256 siblings')
    record_leaf = None if entry is None else entry.to_record()
    if entry is None:
        leaf = proofs.bench_empty_leaf(bench_number)
    else:
        leaf = proofs.bench_entry_leaf(bench_number, target, record_leaf)
    try:
        root = proofs.fold_bench(leaf, siblings, target)
    except ValueError as exc:
        raise ValueError(f'invalid bench proof: {exc}') from exc
    _require(root == bench_anchor, 'bench proof does not match the issuance anchor')

    zero = decide_zero(target, entry, template.default)
    return {
        'ordinal': identity['ordinal'],
        'source': asdict(template.source),
        'raw_strength': template.raw_strength,
        'reference': template.reference,
        'reference_source': template.reference_source,
        'strength': zero.correct(template.raw_strength),
        'zero': _zero_record(zero),
    }


def _zero_record(zero: ZeroDecision):
    return asdict(zero)


def verify_disclosure(anchors, roster, packet):
    report_id, identities = _roster(roster)
    packet_id, rows = _packet(packet)
    _require(packet_id == report_id, 'disclosure report ID differs from the roster')
    _require(len(rows) == len(identities), 'disclosure rows do not match the roster size')
    reviewed = [_review_row(record, identity, anchors)
                for record, identity in zip(rows, identities)]
    total = sum(row['strength'] for row in reviewed if row['strength'] is not None)
    return {'report_id': report_id, 'rows': reviewed, 'total': total}
