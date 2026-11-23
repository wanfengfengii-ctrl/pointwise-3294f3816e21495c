from source.batches import batch_exists
from source.ingest import ingest
from storage import ConflictError, fields, sequence


def initialize_source(db, batches):
    added = []
    for batch in sequence(batches, 'sample batches', allow_empty=True):
        fields(batch, ('batch_id', 'rows'), label='sample batch')
        batch_id = batch['batch_id']
        if batch_exists(db, batch_id):
            continue
        try:
            added.append(ingest(db, batch_id, batch['rows']))
        except ConflictError:
            if not batch_exists(db, batch_id):
                raise
    return tuple(added)
