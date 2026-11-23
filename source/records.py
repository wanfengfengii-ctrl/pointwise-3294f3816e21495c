from dataclasses import dataclass

from source.provenance import ObservationSource, make_observation_source
from storage import fields, integer, sequence, text


@dataclass(frozen=True)
class Observation:
    strength: int
    source: ObservationSource

    @property
    def measurement_id(self):
        return self.source.measurement_id


def validate_observations(batch_id, rows):
    text(batch_id, 'batch ID')
    observations = []
    seen = set()
    for ordinal, row in enumerate(sequence(rows, 'observations'), start=1):
        fields(row, ('measurement_id', 'strength', 'source'), label=f'observation {ordinal}')
        source = make_observation_source(batch_id, row['measurement_id'], ordinal, row['source'])
        if source.measurement_id in seen:
            raise ValueError(f'duplicate measurement {source.measurement_id!r} in batch {batch_id!r}')
        seen.add(source.measurement_id)
        observations.append(Observation(integer(row['strength'], 'raw strength'), source))
    return tuple(observations)
