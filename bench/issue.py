from bench.revision import BenchRevision, get_bench_revision
from processing.envelopes import encode_envelope, issue_number, verify_envelope
from processing.issuance import ensure_issue_table, load_issued, store_issued
from storage import write_transaction


def decode_bench_body(body):
    return BenchRevision.from_record(body)


def issue_bench(db, bench, revision, *, version=1):
    if type(version) is not int or version not in (1, 2):
        raise ValueError('package version must be 1 or 2')
    number = issue_number(bench, revision)
    with write_transaction(db):
        ensure_issue_table(db, 'bench_issue')
        existing = load_issued(db, 'bench_issue', number)
        if existing is not None:
            issued_version, packet = existing
            if issued_version != version:
                raise ValueError(f'bench issue {number!r} is already fixed at version {issued_version}')
            return verify_envelope(packet)
        frozen = get_bench_revision(db, bench, revision)
        packet = encode_envelope('bench', number, frozen.to_record(), version=version)
        envelope = verify_envelope(packet)
        store_issued(db, 'bench_issue', number, version, packet)
    return envelope
