"""Explicit repository-only replay of historical fixtures. No installed engine."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[3]/'tests'),str(Path(__file__).resolve().parents[1]/'scripts')]
from staged_workflow import evaluate as _evaluate, preflight_many as _preflight_many
from production_runtime import compile_jobs as _compile_jobs
_FUNCTIONS={'evaluate':_evaluate,'preflight_many':_preflight_many,'compile_jobs':_compile_jobs}

def _call(name,state,*args,**kwargs):
    import staged_workflow as current
    import production_runtime
    from historical_engines import staged_workflow as old
    from unittest.mock import patch
    function=_FUNCTIONS[name]
    if state.get('execution_mode')=='episode_async_v1':return function(state,*args,**kwargs)
    with patch.object(current,'_evaluate_impl',side_effect=old._evaluate_impl):
        return function(state,*args,**kwargs)
def evaluate(state,*a,**kw):return _call('evaluate',state,*a,**kw)
def preflight_many(state,*a,**kw):return _call('preflight_many',state,*a,**kw)
def compile_jobs(state,*a,**kw):return _call('compile_jobs',state,*a,**kw)
