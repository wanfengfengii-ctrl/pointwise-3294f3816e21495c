from dataclasses import dataclass

from source.batches import store_batch
from source.records import validate_observations


@dataclass(frozen=True)
class ImportReceipt:
    batch_id: str
    row_count: int


def ingest(db, batch_id, rows):
    observations = validate_observations(batch_id, rows)
    store_batch(db, batch_id, observations)
    return ImportReceipt(batch_id, len(observations))
