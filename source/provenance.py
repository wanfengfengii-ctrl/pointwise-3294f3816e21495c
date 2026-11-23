from dataclasses import dataclass

from storage import fields, positive_id, text


@dataclass(frozen=True)
class ObservationSource:
    batch_id: str
    measurement_id: str
    ordinal: int
    locator: str

    @classmethod
    def from_record(cls, record):
        fields(record, ('batch_id', 'measurement_id', 'ordinal', 'locator'), label='observation source')
        return make_observation_source(**record)


def make_observation_source(batch_id, measurement_id, ordinal, locator):
    return ObservationSource(
        text(batch_id, 'batch ID'),
        text(measurement_id, 'measurement ID'),
        positive_id(ordinal, 'sampling position'),
        text(locator, 'observation source'),
    )
