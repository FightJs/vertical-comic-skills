"""Stage immutable inputs and CAS references; NOT a production dispatch protocol.

No runtime capability is enabled here. Existing writers reject the reserved
dispatch_consistency field until all readers/writers and migration are ready.
Candidate publication neither authenticates approval nor proves read-set coverage.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from platform_io import atomic_json, file_lock, portable_relative, check_destination_paths

POLICY = 'dispatch_publication_candidate_v1'
STATUS = 'CANDIDATE_NOT_PRODUCTION'
_SHA = re.compile(r'[0-9a-f]{64}')


def require_legacy(value):
    """Fail closed for explicit future/unknown protocols, including null/false."""
    if 'dispatch_consistency' in value:
        from managed_dispatch import permitted
        if permitted(value): return
        raise ValueError('DISPATCH_PROTOCOL_UNSUPPORTED: dispatch_consistency requires a fully integrated runtime; '
                         'do not remove the marker to downgrade or restore old state')


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                       allow_nan=False)+'\n').encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _scope(value):
    if (not isinstance(value, dict) or set(value) != {'book_id', 'episode_id'} or
            any(not isinstance(v, str) or not v.strip() for v in value.values())):
        raise ValueError('PUBLICATION_SCOPE_HOLD: explicit book/episode required')
    return dict(value)


def _names(names):
    spellings = {}; files = set(names)
    for name in names:
        parts = portable_relative(name).parts
        for length in range(1, len(parts)+1):
            prefix = '/'.join(parts[:length]); key = prefix.casefold()
            if key in spellings and spellings[key] != prefix:
                raise ValueError('PUBLICATION_FILES_HOLD: case alias')
            spellings[key] = prefix
            if length < len(parts) and prefix in files:
                raise ValueError('PUBLICATION_FILES_HOLD: file/directory collision')


def _path(root, relative):
    # Cooperative local filesystems only. Refuse links instead of following a
    # different publication store; hostile races are not an OS access sandbox.
    target = Path(root).absolute() / portable_relative(relative)
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError('PUBLICATION_PATH_HOLD: symlink not supported')
    return target


@contextmanager
def _locked(root):
    root = Path(root).absolute()
    _path(root, 'publication.lock')
    root.mkdir(parents=True, exist_ok=True)
    with file_lock(root/'publication.lock'):
        yield root


def _verify(root, version, scope):
    if not isinstance(version, str) or not _SHA.fullmatch(version):
        raise ValueError('PUBLICATION_VERSION_HOLD')
    base = _path(root, 'versions/'+version)
    manifest = _path(base, 'manifest.json').read_bytes()
    if _sha(manifest) != version:
        raise ValueError('PUBLICATION_CONTENT_CHANGED: manifest')
    data = json.loads(manifest)
    if (data.get('policy') != POLICY or data.get('scope') != _scope(scope) or
            data.get('status') != STATUS or not isinstance(data.get('files'), list) or not data['files']):
        raise ValueError('PUBLICATION_MANIFEST_HOLD')
    names = set(); folded = set()
    _names([row['path'] for row in data['files']])
    for row in data['files']:
        name = row['path']
        path = _path(base/'files', name)
        if name.casefold() in folded or type(row['bytes']) is not int:
            raise ValueError('PUBLICATION_MANIFEST_HOLD: duplicate or invalid file')
        names.add(name); folded.add(name.casefold())
        raw = path.read_bytes()
        if len(raw) != row['bytes'] or _sha(raw) != row['sha256']:
            raise ValueError('PUBLICATION_CONTENT_CHANGED: '+name)
    actual = set()
    for path in base.rglob('*'):
        if path.is_symlink(): raise ValueError('PUBLICATION_PATH_HOLD: symlink')
        if path.is_file(): actual.add(path.relative_to(base).as_posix())
    if actual != {'manifest.json', *('files/'+name for name in names)}:
        raise ValueError('PUBLICATION_CONTENT_CHANGED: membership')
    return data


def publish(root, scope, files):
    """Publish supplied bytes without overwriting versions or changing a head.

    The caller must later prove complete dependency coverage before production
    adoption. Accept bytes, not live paths; an old approval is not re-signed.
    """
    scope = _scope(scope)
    if not isinstance(files, dict) or not files:
        raise ValueError('PUBLICATION_FILES_HOLD')
    rows = []; folded = set()
    _names(list(files))
    for name, raw in sorted(files.items()):
        portable_relative(name)
        if name.casefold() in folded or not isinstance(raw, bytes):
            raise ValueError('PUBLICATION_FILES_HOLD: duplicate or non-bytes')
        folded.add(name.casefold())
        rows.append({'path': name, 'sha256': _sha(raw), 'bytes': len(raw)})
    manifest = _bytes({'policy': POLICY, 'status': STATUS, 'scope': scope, 'files': rows})
    version = _sha(manifest)
    with _locked(root) as root:
        dest = _path(root, 'versions/'+version)
        check_destination_paths(dest, ['manifest.json', *('files/'+r['path'] for r in rows)])
        dest.parent.mkdir(exist_ok=True)
        if dest.exists():
            _verify(root, version, scope)
        else:
            stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=dest.parent))
            try:
                for name, raw in [('manifest.json', manifest), *(('files/'+k, v) for k, v in files.items())]:
                    path = stage/name; path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open('xb') as stream:
                        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                # Only this publisher can create versions while holding the lock.
                # A failure leaves the prior head intact; never replace an object.
                os.rename(stage, dest)
            finally:
                if stage.exists(): shutil.rmtree(stage)
        _verify(root, version, scope)
    return {'version': version, 'status': STATUS, 'scope': scope}


def verify(root, version, scope):
    with _locked(root) as root:
        return _verify(root, version, scope)


def _head(root, scope):
    path = _path(root, 'candidate.json')
    if not path.exists(): return None, None
    raw = path.read_bytes(); value = json.loads(raw)
    if (value.get('policy') != POLICY or value.get('status') != STATUS or
            value.get('scope') != _scope(scope) or type(value.get('revision')) is not int or
            value['revision'] < 1 or not isinstance(value.get('version'), str) or
            not _SHA.fullmatch(value['version'])):
        raise ValueError('PUBLICATION_HEAD_HOLD')
    return value, _sha(raw)


def read_head(root, scope):
    scope = _scope(scope)
    with _locked(root) as root:
        value, token = _head(root, scope)
        if value is not None: _verify(root, value['version'], scope)
    return {'head': value, 'head_sha256': token, 'production_enabled': False}


def switch_candidate(root, scope, version, expected_head_sha256):
    """CAS a candidate reference under the SAME lock as version publication.

    Always advances revision, including a same-version switch (no ABA reuse).
    This is not a production admission decision or a runtime migration API.
    """
    scope = _scope(scope)
    with _locked(root) as root:
        old, token = _head(root, scope)
        if token != expected_head_sha256:
            raise ValueError('PUBLICATION_CONFLICT: candidate head changed; no retry performed')
        # Stage 2 deliberately verifies all bytes under its own candidate lock.
        # Production short-lock consumers do not exist yet.
        _verify(root, version, scope)
        value = {'policy': POLICY, 'status': STATUS, 'scope': scope, 'version': version,
                 'revision': old['revision']+1 if old else 1, 'previous_sha256': token}
        atomic_json(_path(root, 'candidate.json'), value)
        result = {'head': value, 'head_sha256': _sha((root/'candidate.json').read_bytes()),
                  'production_enabled': False}
    return result
