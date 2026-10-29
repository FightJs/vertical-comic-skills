"""Bounded process-local shared validation facts; reuse exact bytes with change detection.

Never persisted PASS records. Each operation has a new read transaction and
rechecks exact content, path targets, missing files and directory observations.
Current state, capacity and authorization gates are never cached as a whole.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar

_POOL=ContextVar('comic_validation_pool',default=None)
NAMES={'runtime_snapshot','toolchain','submission_preflight','approval_scope_map','approval_proof','approval_validation','approval_coverage','approval_index',
       'collection_summary','collection_pair','continuity_context','final_semantic_input','qa_evidence'}
PRIORITY={'runtime_snapshot':3,'toolchain':3,'submission_preflight':2,'approval_scope_map':3,'approval_proof':3,'approval_index':3,'collection_summary':3,'collection_pair':3,
          'continuity_context':2,'qa_evidence':2,'final_semantic_input':2}

class ValidationPool:
    def __init__(self,limit=256, byte_limit=128*1024*1024):
        if type(limit) is not int or limit<1:raise ValueError('Invalid validation cache capacity')
        self.limit=limit;self.entries=OrderedDict();self.queues={1:OrderedDict(),2:OrderedDict(),3:OrderedDict()}
        self.ranks={}
        self.statistics={'hits':0,'misses':0,'invalidations':0,'not_retained':0,
                         'byte_hits':0,'byte_reads':0,'bytes_read':0,'byte_invalidations':0}
        self.byte_limit=byte_limit; self.byte_size=0; self.byte_entries=OrderedDict()

    def file_bytes(self,path):
        """Retain the exact hashed bytes, never just a persisted PASS/mtime.

        Identity, size, mtime AND ctime guard each acquisition; the transaction
        rechecks that identity at publication. Changed content is rehashed.
        Unknown/zero change stamps are deliberately not retained.
        """
        from pathlib import Path
        import hashlib
        path=Path(path); key=str(path)
        before=path.stat()
        stamp=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
        old=self.byte_entries.get(key)
        if old is not None and old[0]==stamp:
            self.byte_entries.move_to_end(key); self.statistics['byte_hits']+=1
            return old
        if old is not None:
            self.byte_size-=len(old[2]);del self.byte_entries[key]
            self.statistics['byte_invalidations']+=1
        data=path.read_bytes(); after=path.stat()
        if stamp!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise ValueError('CHECK_SNAPSHOT_CHANGED: content changed during cache acquisition')
        value=(stamp,hashlib.sha256(data).hexdigest(),data)
        self.statistics['byte_reads']+=1;self.statistics['bytes_read']+=len(data)
        if __import__('os').name!='nt' and stamp[1] and stamp[4] and len(data)<=self.byte_limit:
            while self.byte_entries and self.byte_size+len(data)>self.byte_limit:
                _, evicted=self.byte_entries.popitem(last=False);self.byte_size-=len(evicted[2])
            self.byte_entries[key]=value;self.byte_size+=len(data)
        return value


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
            # digest acquires verified bytes or invalidates on identity/change stamps.
            # Every read transaction retains path and query checks.
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
