import hashlib

from dataclasses import dataclass

from processing import proofs
from storage import canonical_json, fields, parse_json, text


@dataclass(frozen=True)
class Envelope:
    version: int
    kind: str
    number: str
    digest: str
    body: dict
    packet: bytes


def issue_number(name, revision):
    text(name, 'package owner')
    text(revision, 'package revision')
    return f'{len(name)}:{name}:{revision}'


def parse_issue_number(number):
    """Inverse of :func:`issue_number`; raises ``ValueError`` when malformed."""
    text(number, 'issue number')
    colon = number.find(':')
    if colon < 1:
        raise ValueError('malformed issue number')
    try:
        length = int(number[:colon], 10)
    except ValueError as exc:
        raise ValueError('malformed issue number') from exc
    rest = number[colon + 1:]
    if length < 1 or len(rest) < length + 1 or rest[length] != ':':
        raise ValueError('malformed issue number')
    name, revision = rest[:length], rest[length + 1:]
    if issue_number(name, revision) != number:
        raise ValueError('malformed issue number')
    return name, revision


def _header(kind, number, body):
    if kind not in ('template', 'bench'):
        raise ValueError('unknown package kind')
    text(number, 'issue number')
    if not isinstance(body, dict):
        raise ValueError('package body must be an object')
    return {'version': 1, 'kind': kind, 'number': number, 'body': body}


def _digest(header):
    return hashlib.sha256(canonical_json(header).encode('ascii')).hexdigest()


def _anchor(kind, number, body):
    """The version 2 issuance anchor over the frozen body.

    The anchor is fixed at first issue time and depends only on the version,
    the package kind, the issue number and the frozen body; it is produced
    before any disclosure row or application mount is selected.
    """
    if kind == 'template':
        records = body['rows']
        return proofs.template_anchor(number, records)
    return proofs.bench_anchor(number, body['entries'])


def encode_envelope(kind, number, body, *, version=1):
    if type(version) is not int or version not in (1, 2):
        raise ValueError('package version must be 1 or 2')
    header = _header(kind, number, body)
    if version == 1:
        digest = _digest(header)
    else:
        try:
            digest = _anchor(kind, number, body)
        except (KeyError, TypeError) as exc:
            raise ValueError(f'invalid package body for version 2: {exc}') from exc
    return canonical_json({**header, 'version': version, 'digest': digest}).encode('utf-8')


def verify_envelope(packet):
    if not isinstance(packet, bytes):
        raise ValueError('package must be bytes')
    try:
        record = parse_json(packet.decode('utf-8'))
        fields(record, ('version', 'kind', 'number', 'body', 'digest'), label='package')
        version = record['version']
        if type(version) is not int or version not in (1, 2):
            raise ValueError('unsupported package version')
        if version == 1:
            header = _header(record['kind'], record['number'], record['body'])
            digest = _digest(header)
        else:
            if record['kind'] not in ('template', 'bench'):
                raise ValueError('unknown package kind')
            text(record['number'], 'issue number')
            if not isinstance(record['body'], dict):
                raise ValueError('package body must be an object')
            digest = _anchor(record['kind'], record['number'], record['body'])
        if record['digest'] != digest:
            raise ValueError('package digest mismatch')
        canonical_packet = canonical_json(record).encode('utf-8')
    except (UnicodeError, RecursionError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'invalid envelope: {exc}') from exc
    return Envelope(version, record['kind'], record['number'], digest, record['body'], canonical_packet)
