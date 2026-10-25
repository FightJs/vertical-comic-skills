"""Run a frozen read-only checker with live stderr and durable partial logs."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time


def run(argv, *, cwd, timeout, stdout_path, stderr_path, progress_stream=None, budget_path=None):
    """Stdout remains machine JSON. No pipe can fill while the parent waits."""
    sink=progress_stream if progress_stream is not None else sys.stderr
    from runtime_clock import require_running
    budget_root=budget_path or cwd
    budget=require_running(budget_root)
    admitted_timeout=min(timeout,budget['remaining_seconds']) if budget and budget.get('state')=='RUNNING' else timeout
    stdout_path,stderr_path=Path(stdout_path),Path(stderr_path)
    with stdout_path.open('x',encoding='utf-8',newline='\n') as output, \
         stderr_path.open('x',encoding='utf-8',newline='\n') as diagnostic:
        process=subprocess.Popen(argv,cwd=cwd,stdout=output,stderr=subprocess.PIPE,
                                 text=True,encoding='utf-8',errors='replace')
        log_errors=[]
        def drain():
            try:
                for line in process.stderr:
                    # Keep draining after a disk error: a full pipe must not hang
                    # the checker or erase the evidence already written.
                    if not log_errors:
                        try:diagnostic.write(line);diagnostic.flush()
                        except (OSError,ValueError) as exc:log_errors.append(exc)
                    try:sink.write(line);sink.flush()
                    except Exception:pass  # Display is optional; saved evidence is not.
            except Exception as exc:
                log_errors.append(exc)
                if process.poll() is None:process.kill()
        reader=threading.Thread(target=drain,daemon=True)
        reader.start()
        timed_out=False
        try:
            deadline=time.monotonic()+admitted_timeout
            while process.poll() is None:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise subprocess.TimeoutExpired(argv,admitted_timeout)
                try:process.wait(timeout=min(0.5,remaining))
                except subprocess.TimeoutExpired:
                    if budget and budget.get('state')=='RUNNING':require_running(budget_root)
        except subprocess.TimeoutExpired:
            timed_out=True
            process.kill();process.wait()
        except BaseException:
            if process.poll() is None:process.kill()
            process.wait()
            raise
        finally:
            reader.join();process.stderr.close()
        if log_errors:
            raise OSError('Audit stderr evidence could not be saved completely: '+str(log_errors[0])) from log_errors[0]
    stdout=stdout_path.read_text(encoding='utf-8')
    stderr=stderr_path.read_text(encoding='utf-8')
    if timed_out:raise subprocess.TimeoutExpired(argv,admitted_timeout,output=stdout,stderr=stderr)
    return subprocess.CompletedProcess(argv,process.returncode,stdout,stderr)


def last_progress(stderr):
    for line in reversed(stderr.splitlines()):
        try:value=json.loads(line)
        except (ValueError,TypeError):continue
        if isinstance(value,dict) and value.get('policy')=='audit_progress_v1':return value
    return None
