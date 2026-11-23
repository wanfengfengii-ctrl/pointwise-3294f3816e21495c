def _parts(path, *, allow_empty):
    if not isinstance(path, str) or (not path.strip() and (path or not allow_empty)):
        raise ValueError('invalid virtual bench path')
    if path.startswith('/') or '\\' in path or '\x00' in path:
        raise ValueError(f'expected a relative virtual bench path: {path!r}')
    try:
        path.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError('virtual bench path must be valid Unicode') from exc
    return path.split('/')


def _walk(parts, stack):
    for part in parts:
        if part in ('', '.'):
            continue
        if part == '..':
            if not stack:
                raise ValueError('virtual path leaves the bench root')
            stack.pop()
        else:
            stack.append(part)
    return stack


def normalize_entry_path(path):
    return '/'.join(_walk(_parts(path, allow_empty=True), []))


def validate_relative_reference(reference):
    _parts(reference, allow_empty=False)
    return reference


def resolve_relative(mount, reference):
    stack = _walk(_parts(mount, allow_empty=True), [])
    return '/'.join(_walk(_parts(reference, allow_empty=False), stack))
