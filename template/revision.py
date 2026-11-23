from dataclasses import asdict, dataclass

from bench.paths import validate_relative_reference
from source.provenance import ObservationSource
from storage import (
    ConflictError, canonical_json, decode_integer, encode_integer, fields,
    has_table, parse_json, sequence, text, write_transaction,
)
from template.calibration import DefaultZero
from template.draft import reference_source, select_observations


@dataclass(frozen=True)
class FrozenTemplateRow:
    source: ObservationSource
    raw_strength: int
    reference: str
    reference_source: str | None
    default: DefaultZero | None

    def to_record(self):
        return {
            'source': asdict(self.source),
            'raw_strength': encode_integer(self.raw_strength),
            'reference': self.reference,
            'reference_source': self.reference_source,
            'default': None if self.default is None else self.default.to_record(),
        }

    @classmethod
    def from_record(cls, record):
        fields(
            record, ('source', 'raw_strength', 'reference', 'reference_source', 'default'),
            label='fixed template row',
        )
        default = record['default']
        return cls(
            ObservationSource.from_record(record['source']),
            decode_integer(record['raw_strength']),
            validate_relative_reference(record['reference']),
            reference_source(record['reference_source']),
            None if default is None else DefaultZero.from_record(default),
        )


@dataclass(frozen=True)
class FrozenTemplate:
    name: str
    revision: str
    rows: tuple[FrozenTemplateRow, ...]

    def to_record(self):
        return {'name': self.name, 'revision': self.revision, 'rows': [row.to_record() for row in self.rows]}

    @classmethod
    def from_record(cls, record):
        fields(record, ('name', 'revision', 'rows'), label='template revision')
        return cls(
            text(record['name'], 'template name'),
            text(record['revision'], 'template revision'),
            tuple(FrozenTemplateRow.from_record(row) for row in sequence(record['rows'], 'fixed template rows')),
        )


def freeze_template(db, draft, revision):
    text(revision, 'template revision')
    rows = tuple(
        FrozenTemplateRow(observation.source, observation.strength, rule.reference, rule.reference_source, rule.default)
        for rule, observation in select_observations(db, draft)
    )
    frozen = FrozenTemplate(draft.name, revision, rows)
    body = canonical_json(frozen.to_record())
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS template_revision (
                name TEXT NOT NULL,
                revision TEXT NOT NULL,
                body TEXT NOT NULL,
                PRIMARY KEY (name, revision)
            )
        ''')
        cursor = db.execute(
            'INSERT INTO template_revision VALUES (?, ?, ?) ON CONFLICT (name, revision) DO NOTHING',
            (frozen.name, revision, body),
        )
        if cursor.rowcount != 1:
            raise ConflictError(f'template revision already exists: {frozen.name!r}, {revision!r}')
    return frozen


def get_template_revision(db, name, revision):
    text(name, 'template name')
    text(revision, 'template revision')
    row = None
    if has_table(db, 'template_revision'):
        row = db.execute(
            'SELECT body FROM template_revision WHERE name = ? AND revision = ?', (name, revision)
        ).fetchone()
    if row is None:
        raise KeyError(f'unknown template revision {name!r}, {revision!r}')
    return FrozenTemplate.from_record(parse_json(row[0]))
