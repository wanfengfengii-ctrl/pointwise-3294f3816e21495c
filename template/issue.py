from processing.envelopes import encode_envelope, issue_number, verify_envelope
from processing.issuance import ensure_issue_table, load_issued, store_issued
from storage import write_transaction
from template.revision import FrozenTemplate, get_template_revision


def decode_template_body(body):
    return FrozenTemplate.from_record(body)


def issue_template(db, name, revision, *, version=1):
    """Issue one frozen template revision.

    ``version`` is 1 (the original convention) or 2 (with a partial-disclosure
    anchor).  The anchor is fixed at first issue; re-issuing the same revision
    at the same version returns the original packet, and asking for an already
    issued revision at another version is refused.
    """
    if type(version) is not int or version not in (1, 2):
        raise ValueError('package version must be 1 or 2')
    number = issue_number(name, revision)
    with write_transaction(db):
        ensure_issue_table(db, 'template_issue')
        existing = load_issued(db, 'template_issue', number)
        if existing is not None:
            issued_version, packet = existing
            if issued_version != version:
                raise ValueError(f'template issue {number!r} is already fixed at version {issued_version}')
            return verify_envelope(packet)
        frozen = get_template_revision(db, name, revision)
        packet = encode_envelope('template', number, frozen.to_record(), version=version)
        envelope = verify_envelope(packet)
        store_issued(db, 'template_issue', number, version, packet)
    return envelope
