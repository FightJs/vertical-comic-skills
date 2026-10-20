"""Transaction-local derived evidence. No persistent PASS or approval storage."""
import copy
import json


def _readonly(*args, **kwargs):
    raise TypeError('Read-only audit data; request a mutable JSON copy before editing')


class ReadOnlyDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _readonly

    def __deepcopy__(self, memo):
        result = {}
        memo[id(self)] = result
        result.update((copy.deepcopy(k, memo), copy.deepcopy(v, memo)) for k, v in self.items())
        return result


class ReadOnlyList(list):
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
    return value


def content_key(value):
    # Full content, not object identity: callers may mutate inline decisions.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def derived(namespace, key, compute, *, accept=lambda value: True):
    """Reuse an immutable result only after rechecking every captured dependency."""
    from codex_reference_contract import _FILE_SESSION, digest
    memo = _FILE_SESSION.get()
    if memo is None:
        return freeze(compute())
    token = (namespace, key)
    counters = memo['audit_statistics'].setdefault(namespace, {'runs': 0, 'hits': 0})
    saved = memo['derived'].get(token)
    if saved is not None:
        for path in saved[1]:
            digest(path)
        counters['hits'] += 1
        return saved[0]
    counters['runs'] += 1
    dependencies = set()
    memo['dependency_stack'].append(dependencies)
    try:
        result = freeze(compute())
        if accept(result):
            memo['derived'][token] = (result, tuple(sorted(dependencies)))
        return result
    finally:
        memo['dependency_stack'].pop()
        if memo['dependency_stack']:
            memo['dependency_stack'][-1].update(dependencies)
