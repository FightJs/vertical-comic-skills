"""Transaction-local derived evidence. No persistent PASS or approval storage."""
import copy
import json


def _readonly(*args, **kwargs):
    raise TypeError('Read-only audit data; request a mutable JSON copy before editing')


class ReadOnlyDict(dict):
    def __init__(self, *args, **kwargs):
        if getattr(self, '_sealed', False):
            _readonly()
        super().__init__(*args, **kwargs)
        object.__setattr__(self, '_sealed', True)

    __setattr__ = __delattr__ = _readonly
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _readonly

    def __deepcopy__(self, memo):
        result = {}
        memo[id(self)] = result
        result.update((copy.deepcopy(k, memo), copy.deepcopy(v, memo)) for k, v in self.items())
        return result


class ReadOnlyList(list):
    def __init__(self, *args, **kwargs):
        if getattr(self, '_sealed', False):
            _readonly()
        super().__init__(*args, **kwargs)
        object.__setattr__(self, '_sealed', True)

    __setattr__ = __delattr__ = _readonly
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _readonly

    def __deepcopy__(self, memo):
        result = []
        memo[id(self)] = result
        result.extend(copy.deepcopy(v, memo) for v in self)
        return result


def freeze(value):
    """Preserve JSON dict/list semantics for existing validators, prohibit edits."""
    if isinstance(value, (ReadOnlyDict, ReadOnlyList)):
        return value
    if isinstance(value, dict):
        return ReadOnlyDict((k, freeze(v)) for k, v in value.items())
    if isinstance(value, list):
        return ReadOnlyList(freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(freeze(v) for v in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError('Audit cache values must contain only JSON data and tuples')


def content_key(value):
    # Full content, not object identity: callers may mutate inline decisions.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def derived(namespace, key, compute, *, accept=lambda value: True, options=None):
    """Reuse an immutable result only after rechecking every captured dependency."""
    from runtime_pipeline import poll_budget
    poll_budget()
    from codex_reference_contract import _FILE_SESSION, recheck_dependencies, _valid, READ_POLICY
    memo = _FILE_SESSION.get()
    if memo is None:
        return freeze(compute())
    _valid()
    token = content_key([READ_POLICY, namespace, key, options])
    counters = memo['audit_statistics'].setdefault(namespace, {'runs': 0, 'hits': 0})
    saved = memo['derived'].get(token)
    from validation_pool import _POOL
    pool = _POOL.get()
    if saved is None and pool is not None:
        saved = pool.get(namespace, token, memo)
        if saved is not None:memo['derived'][token] = saved
    if saved is not None:
        from validation_pool import NAMES
        if pool is not None and namespace in NAMES:
            # This operation is read-only and cannot publish until file_session
            # verifies its full read set. Carry the transitive dependencies,
            # rather than re-stat the same closure for every panel/cache hit.
            if memo['dependency_stack']:memo['dependency_stack'][-1].update(saved[1])
        else:
            recheck_dependencies(saved[1])
        counters['hits'] += 1
        return saved[0]
    counters['runs'] += 1
    dependencies = set()
    memo['dependency_stack'].append(dependencies)
    try:
        result = freeze(compute())
        if accept(result):
            captured = tuple(sorted(dependencies, key=repr))
            memo['derived'][token] = (result, captured)
            if pool is not None:pool.put(namespace, token, result, captured, memo)
        return result
    finally:
        memo['dependency_stack'].pop()
        if memo['dependency_stack']:
            memo['dependency_stack'][-1].update(dependencies)
