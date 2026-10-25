"""Bounded process-local shared validation facts; always rehash dependencies.

Never persisted PASS records. Each operation has a new read transaction and
rechecks exact content, path targets, missing files and directory observations.
Current state, capacity and authorization gates are never cached as a whole.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar

_POOL=ContextVar('comic_validation_pool',default=None)
NAMES={'approval_proof','approval_validation','approval_coverage','approval_index',
       'collection_summary','collection_pair','continuity_context','final_semantic_input','qa_evidence'}
PRIORITY={'approval_proof':3,'approval_index':3,'collection_summary':3,'collection_pair':3,
          'continuity_context':2,'qa_evidence':2,'final_semantic_input':2}

class ValidationPool:
    def __init__(self,limit=256):
        if type(limit) is not int or limit<1:raise ValueError('Invalid validation cache capacity')
        self.limit=limit;self.entries=OrderedDict();self.queues={1:OrderedDict(),2:OrderedDict(),3:OrderedDict()}
        self.ranks={}
        self.statistics={'hits':0,'misses':0,'invalidations':0,'not_retained':0}

    def _drop(self,token):
        self.entries.pop(token,None)
        rank=self.ranks.pop(token,None)
        if rank is not None:self.queues[rank].pop(token,None)

    def _touch(self,token):
        self.entries.move_to_end(token);self.queues[self.ranks[token]].move_to_end(token)

    def get(self,namespace,token,memo):
        if namespace not in NAMES:return None
        saved=self.entries.get(token)
        if saved is None:
            self.statistics['misses']+=1;return None
        result,dependencies,hashes,observations=saved
        from codex_reference_contract import digest,recheck_dependencies
        from pathlib import Path
        from audit_cache import content_key
        try:
            # digest reads real bytes once in this new operation, not a stamp
            # inherited from an earlier operation. Cached results grant no rights.
            for name,expected in hashes:
                target=memo['paths'].get(name)
                current=memo['files'].get(target)
                actual=current[1] if current is not None else digest(Path(name))
                if actual!=expected:raise LookupError('content changed')
            # Reuse only observations made in this fresh read transaction.
            # Its boundary still verifies every positive/negative/query version.
            unknown=[dep for dep in dependencies if not isinstance(dep,str) and dep not in memo['observations']]
            recheck_dependencies(unknown)
            if any(content_key(memo['observations'].get(k))!=v for k,v in observations):
                raise LookupError('query changed')
        except (OSError,LookupError):
            self._drop(token);self.statistics['invalidations']+=1;return None
        self._touch(token);self.statistics['hits']+=1
        return result,dependencies

    def put(self,namespace,token,result,dependencies,memo):
        if namespace not in NAMES:return
        from audit_cache import content_key
        hashes=[];observations=[]
        for dep in dependencies:
            if isinstance(dep,str):
                hashes.append((dep,memo['files'][memo['paths'][dep]][1]))
            else:observations.append((dep,content_key(memo['observations'][dep])))
        # Per-panel subset queries must not evict common proofs and contexts.
        # Keep the same strict bound, evicting the oldest lowest-priority fact.
        rank=PRIORITY.get(namespace,1)
        self._drop(token)
        if len(self.entries)>=self.limit:
            lowest=next(k for k in sorted(self.queues) if self.queues[k])
            if lowest>rank:
                self.statistics['not_retained']+=1;return
            self._drop(next(iter(self.queues[lowest])))
        self.entries[token]=(result,dependencies,hashes,observations)
        self.ranks[token]=rank;self.queues[rank][token]=None

@contextmanager
def session(pool):
    token=_POOL.set(pool)
    try:yield
    finally:_POOL.reset(token)
