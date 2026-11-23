from dataclasses import dataclass

from report.receipt import FirstReceipt, load_first_receipt
from report.snapshots import ReportSnapshot, load_snapshot
from storage import positive_id


@dataclass(frozen=True)
class ReadReport:
    snapshot: ReportSnapshot
    first_receipt: FirstReceipt


def read(db, report_id):
    positive_id(report_id, 'report ID')
    snapshot = load_snapshot(db, report_id)
    return ReadReport(snapshot, load_first_receipt(db, report_id))
