from dataclasses import dataclass

from bench.paths import validate_relative_reference
from source.batches import load_batch
from storage import fields, sequence, text
from template.calibration import DefaultZero


@dataclass(frozen=True)
class DraftRow:
    batch_id: str
    measurement_id: str
    reference: str
    reference_source: str | None
    default: DefaultZero | None


def reference_source(value):
    return None if value is None else text(value, 'reference source')


def _draft_row(record):
    fields(
        record,
        ('batch_id', 'measurement_id', 'reference'),
        ('reference_source', 'default'),
        label='draft row',
    )
    default = record.get('default')
    if default is not None:
        fields(default, ('value', 'source'), label='draft default zero')
        default = DefaultZero(default['value'], default['source'])
    return DraftRow(
        text(record['batch_id'], 'batch ID'),
        text(record['measurement_id'], 'measurement ID'),
        validate_relative_reference(record['reference']),
        reference_source(record.get('reference_source')),
        default,
    )


class TemplateDraft:
    def __init__(self, name, rows):
        self._name = text(name, 'template name')
        self.replace_rows(rows)

    @property
    def name(self):
        return self._name

    @property
    def rows(self):
        return self._rows

    def replace_rows(self, rows):
        self._rows = tuple(_draft_row(record) for record in sequence(rows, 'draft rows'))


def build_draft(name, rows):
    return TemplateDraft(name, rows)


def select_observations(db, draft):
    by_batch = {}
    for row in draft.rows:
        if row.batch_id not in by_batch:
            by_batch[row.batch_id] = {item.measurement_id: item for item in load_batch(db, row.batch_id)}
        observations = by_batch[row.batch_id]
        if row.measurement_id not in observations:
            raise KeyError(f'unknown measurement {row.measurement_id!r} in batch {row.batch_id!r}')
        yield row, observations[row.measurement_id]
