import hashlib
from dataclasses import dataclass

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


def _header(kind, number, body):
    if kind not in ('template', 'bench'):
        raise ValueError('unknown package kind')
    text(number, 'issue number')
    if not isinstance(body, dict):
        raise ValueError('package body must be an object')
    return {'version': 1, 'kind': kind, 'number': number, 'body': body}


def _digest(header):
    return hashlib.sha256(canonical_json(header).encode('ascii')).hexdigest()


def encode_envelope(kind, number, body):
    header = _header(kind, number, body)
    return canonical_json({**header, 'digest': _digest(header)}).encode('utf-8')


def verify_envelope(packet):
    if not isinstance(packet, bytes):
        raise ValueError('package must be bytes')
    try:
        record = parse_json(packet.decode('utf-8'))
        fields(record, ('version', 'kind', 'number', 'body', 'digest'), label='V1 package')
        if type(record['version']) is not int or record['version'] != 1:
            raise ValueError('unsupported package version')
        header = _header(record['kind'], record['number'], record['body'])
        digest = _digest(header)
        if record['digest'] != digest:
            raise ValueError('package digest mismatch')
        canonical_packet = canonical_json(record).encode('utf-8')
    except (UnicodeError, RecursionError, ValueError) as exc:
        raise ValueError(f'invalid envelope: {exc}') from exc
    return Envelope(1, record['kind'], record['number'], digest, record['body'], canonical_packet)
