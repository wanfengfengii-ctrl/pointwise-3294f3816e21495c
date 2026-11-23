"""Version 2 issuance anchors and partial (limited-row) proofs.

The version 2 anchor commits to the whole frozen body without revealing it:

* template issues are committed with an ordered binary Merkle tree over the
  frozen rows, so a disclosure can prove one row at one row position without
  carrying the other rows' original readings;
* bench issues are committed with a 256 bit sparse Merkle tree keyed by
  ``sha256(path)``, so a disclosure can prove that one canonical path holds a
  given entry *or* that the path holds no entry at all.

Every leaf payload is bound to the package version, kind and issue number, so
an anchor can never be replayed for another issue.  The hash organisation is an
implementation detail of this project (see DISCLOSURE.md).
"""

import hashlib
import re

from storage import canonical_json

TEMPLATE_DOMAIN = 'disclosure/template'
BENCH_DOMAIN = 'disclosure/bench'
BENCH_DEPTH = 256

_TAG_LEAF = b'\x00'
_TAG_NODE = b'\x01'
_HEX = re.compile(r'[0-9a-f]{64}')


def _hash(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.digest()


def _object(value):
    return canonical_json(value).encode('ascii')


def to_hex(value):
    return value.hex()


def from_hex(value, label):
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise ValueError(f'{label} must be 64 lowercase hex characters')
    return bytes.fromhex(value)


# --------------------------------------------------------------------------
# Ordered Merkle tree for the frozen template rows
# --------------------------------------------------------------------------

def template_leaf(number, count, index, record):
    payload = {
        'domain': TEMPLATE_DOMAIN,
        'version': 2,
        'number': number,
        'count': count,
        'index': index,
        'row': record,
    }
    return _hash(_TAG_LEAF, _object(payload))


def _split(count):
    """Largest power of two strictly smaller than ``count`` (RFC 6962 style)."""
    half = 1
    while half * 2 < count:
        half *= 2
    return half


def _root(nodes):
    count = len(nodes)
    if count == 0:
        raise ValueError('template issue has no rows')
    if count == 1:
        return nodes[0]
    half = _split(count)
    return _hash(_TAG_NODE, _root(nodes[:half]), _root(nodes[half:]))


def template_anchor(number, records):
    count = len(records)
    if not count:
        raise ValueError('template issue has no rows')
    return to_hex(_root([template_leaf(number, count, index + 1, record)
                         for index, record in enumerate(records)]))


def _template_nodes(number, records):
    count = len(records)
    if not count:
        raise ValueError('template issue has no rows')
    return count, [template_leaf(number, count, index + 1, record)
                   for index, record in enumerate(records)]


def _prove(nodes, index):
    count = len(nodes)
    if count == 1:
        return []
    half = _split(count)
    if index < half:
        return [to_hex(_root(nodes[half:]))] + _prove(nodes[:half], index)
    return [to_hex(_root(nodes[:half]))] + _prove(nodes[half:], index - half)


def template_proof(number, records, index):
    _, nodes = _template_nodes(number, records)
    if type(index) is not int or index < 1 or index > len(nodes):
        raise ValueError('template row position is outside the issue')
    return _prove(nodes, index - 1)


def fold_template(leaf, siblings, index, count):
    if type(count) is not int or count < 1:
        raise ValueError('template proof count is invalid')
    if type(index) is not int or index < 1 or index > count:
        raise ValueError('template proof index is invalid')
    return _fold_template(leaf, list(siblings), index - 1, count)


def _fold_template(node, siblings, index, count):
    if count == 1:
        if siblings:
            raise ValueError('template proof has trailing siblings')
        return node
    if not siblings:
        raise ValueError('template proof is missing siblings')
    half = _split(count)
    sibling = siblings.pop(0)
    if index < half:
        left = _fold_template(node, siblings, index, half)
        return _hash(_TAG_NODE, left, sibling)
    right = _fold_template(node, siblings, index - half, count - half)
    return _hash(_TAG_NODE, sibling, right)


# --------------------------------------------------------------------------
# Sparse Merkle tree for the frozen bench entries
# --------------------------------------------------------------------------

def _path_key(path):
    return int.from_bytes(hashlib.sha256(path.encode('utf-8')).digest(), 'big')


def bench_empty_leaf(number):
    return _hash(_TAG_LEAF, _object({
        'domain': BENCH_DOMAIN,
        'version': 2,
        'number': number,
        'empty': True,
    }))


def bench_entry_leaf(number, path, record):
    return _hash(_TAG_LEAF, _object({
        'domain': BENCH_DOMAIN,
        'version': 2,
        'number': number,
        'path': path,
        'entry': record,
    }))


def _empty_ladder(number):
    ladder = [bench_empty_leaf(number)]
    for _ in range(BENCH_DEPTH):
        previous = ladder[-1]
        ladder.append(_hash(_TAG_NODE, previous, previous))
    return ladder


def _entry_level(number, entries):
    level = {}
    for record in entries:
        path = record['path']
        key = _path_key(path)
        if key in level:
            raise ValueError('bench issue repeats a path key')
        level[key] = bench_entry_leaf(number, path, record)
    return level


def _bench_levels(number, entries):
    empty = _empty_ladder(number)
    levels = [_entry_level(number, entries)]
    for depth in range(BENCH_DEPTH):
        pairs = {}
        for key, value in levels[-1].items():
            parent = key >> 1
            pair = pairs.get(parent)
            if pair is None:
                pair = [None, None]
                pairs[parent] = pair
            bit = key & 1
            if pair[bit] is not None:
                raise ValueError('sparse Merkle key collision')
            pair[bit] = value
        parents = {}
        for parent, pair in pairs.items():
            left = empty[depth] if pair[0] is None else pair[0]
            right = empty[depth] if pair[1] is None else pair[1]
            parents[parent] = _hash(_TAG_NODE, left, right)
        levels.append(parents)
    return levels, empty


def bench_anchor(number, entries):
    levels, empty = _bench_levels(number, entries)
    return to_hex(levels[BENCH_DEPTH].get(0, empty[BENCH_DEPTH]))


def bench_proof(number, entries, path):
    levels, empty = _bench_levels(number, entries)
    key = _path_key(path)
    siblings = []
    for depth in range(BENCH_DEPTH):
        sibling_key = ((key >> 1) << 1) | (1 - (key & 1))
        siblings.append(to_hex(levels[depth].get(sibling_key, empty[depth])))
        key >>= 1
    return siblings


def fold_bench(leaf, siblings, path):
    siblings = list(siblings)
    if len(siblings) != BENCH_DEPTH:
        raise ValueError('bench proof must carry 256 siblings')
    key = _path_key(path)
    node = leaf
    for sibling in siblings:
        if key & 1:
            node = _hash(_TAG_NODE, sibling, node)
        else:
            node = _hash(_TAG_NODE, node, sibling)
        key >>= 1
    return node
