"""Portable process locks, durable JSON writes and filesystem names.

Only file operations may retry. This module never submits or retries image jobs.
Lock sidecars are persistent: unlinking them could split competing lock owners.
"""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
import errno
import hashlib
import json
import os
import re
import sys
import tempfile
import time


def codex_home():
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser().resolve()


def configure_stdio():
    """CLI JSON and diagnostics use UTF-8 even when redirected on Windows."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict')


@contextmanager
def file_lock(path, *, timeout=60.0):
    if timeout < 0:
        raise ValueError('Lock timeout must be nonnegative')
    path = Path(path)
    # Callers own parent creation and transaction scope.
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b'\0')
                stream.flush()
            def acquire():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(stream, fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'FILE_LOCK_TIMEOUT: {path}; no state changed') from exc
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield stream
        finally:
            release()


def replace_file(source, destination):
    """Bounded retry for transient Windows sharing violations only."""
    for attempt in range(6):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            if os.name != 'nt' or getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


def atomic_json(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        # The temporary handle is closed before replacement (required on Windows).
        replace_file(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', re.I)


def portable_relative(value):
    """Validate a serialized package path; never repair signed input silently."""
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('路径须为明确的包内POSIX相对路径')
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or str(path) != value or '..' in path.parts:
        raise ValueError('路径越界或非规范相对路径: ' + value)
    for part in path.parts:
        if (part.endswith((' ', '.')) or _RESERVED.match(part) or
                any(ord(c) < 32 or c in '<>:"|?*' for c in part) or
                len(part.encode('utf-16-le')) // 2 > 255):
            raise ValueError('Windows不支持的包内文件名: ' + value)
    return path


def book_directory(book):
    """Only the generated directory name changes; the actual book ID stays exact."""
    if not isinstance(book, str) or not book.strip():
        raise ValueError('书名不能为空')
    try:
        if len(portable_relative(book).parts) == 1 and len(book) <= 60:
            return book
    except ValueError:
        pass
    stem = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', book).strip(' .')[:48] or 'book'
    return 'book-' + stem + '-' + hashlib.sha256(book.encode('utf-8')).hexdigest()[:10]


def skill_entry_key(value):
    """Read a provenance path from either OS without interpreting it as local."""
    cls = PureWindowsPath if '\\' in value or PureWindowsPath(value).drive else PurePosixPath
    path = cls(value)
    if path.name != 'SKILL.md' or not path.parent.name.startswith('vertical-comic-'):
        raise ValueError('无效的冻结Skill身份路径')
    return path.parent.name


def check_destination_paths(root, names):
    """Catch MAX_PATH failures before copying/extracting; never change OS settings."""
    if os.name != 'nt':
        return
    root = Path(root).resolve()
    longest = max((str(root / name) for name in names), key=len, default=str(root))
    if len(longest.encode('utf-16-le')) // 2 < 248 or str(root).startswith('\\\\?\\'):
        return
    import winreg
    enabled = False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SYSTEM\CurrentControlSet\Control\FileSystem') as key:
            enabled = winreg.QueryValueEx(key, 'LongPathsEnabled')[0] == 1
    except OSError:
        pass
    if not enabled:
        raise ValueError('WINDOWS_PATH_HOLD: 当前系统未启用长路径，目标路径过长；'
                         '请选择更短的输出目录或CODEX_HOME，再重新运行。目标: ' + longest)
