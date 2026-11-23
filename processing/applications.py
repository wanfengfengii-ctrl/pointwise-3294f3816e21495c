from dataclasses import dataclass

from bench.paths import normalize_entry_path
from processing.intake import ReceivedPackage, get_received
from storage import sequence


@dataclass(frozen=True)
class ApplicationItem:
    template_receipt: int
    bench_receipt: int
    mount: str


@dataclass(frozen=True)
class BoundApplication:
    index: int
    template: ReceivedPackage
    bench: ReceivedPackage
    mount: str


def bind_applications(db, items):
    bound = []
    for index, item in enumerate(sequence(items, 'application list'), start=1):
        if not isinstance(item, ApplicationItem):
            raise ValueError(f'application {index} must be an ApplicationItem')
        template = get_received(db, item.template_receipt, kind='template')
        bench = get_received(db, item.bench_receipt, kind='bench')
        mount = normalize_entry_path(item.mount)
        bound.append(BoundApplication(index, template, bench, mount))
    return tuple(bound)
