#!/usr/bin/env python3
"""Prepare Codex's child-agent limit; never infer a live session's capacity."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import tomllib

TARGET = 6


def config_path():
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'


def parse(raw):
    return tomllib.loads(raw.decode('utf-8-sig'))


def inspect(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('CONFIG_SYMLINK: 配置为符号链接，未修改')
    raw = path.read_bytes() if path.exists() else b''
    data = parse(raw)
    agents = data.get('agents', {})
    if not isinstance(agents, dict):
        raise ValueError('CONFIG_INVALID: agents 必须为配置表')
    current, legacy = agents.get('max_concurrent_threads_per_session'), agents.get('max_threads')
    for value in (current, legacy):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError('CONFIG_INVALID: agent 上限必须为正整数')
    if current is not None and legacy is not None and current != legacy:
        raise ValueError('CONFIG_CONFLICT: 新旧 agent 上限不一致，未修改')
    enabled = agents.get('enabled', True)
    if type(enabled) is not bool:
        raise ValueError('CONFIG_INVALID: agents.enabled 必须为布尔值')
    return raw, data, (current if current is not None else legacy), enabled


def ensure(path=None, *, target=TARGET, write=True):
    path = Path(path) if path is not None else config_path()
    report = {'target_subagents': target, 'target_total_including_coordinator': target + 1,
              'config_path': str(path), 'configuration_changed': False,
              'current_session_capacity': None, 'current_session_capacity_status': 'unknown',
              'next_action': '按宿主实际可用槽位调度；写入配置不代表当前会话已生效'}
    try:
        if type(target) is not int or target < 1:
            raise ValueError('CONFIG_INVALID: 目标须为正整数')
        raw, data, limit, enabled = inspect(path)
        report.update(previous_configured_limit=limit, configured_limit=limit,
                      enabled=enabled, configuration_validated=True)
        if enabled and limit is not None and limit >= target:
            report['status'] = 'CONFIGURED'; return report
        if not write:
            report['status'] = 'CONFIGURATION_NEEDED'; return report
        # Refuse ambiguous layouts rather than rewriting other TOML fields.
        text = raw.decode('utf-8-sig'); newline = '\r\n' if '\r\n' in text else '\n'
        pattern = re.compile(r'(?m)^\s*\[agents\]\s*(?:\#.*)?\r?$')
        sections = list(pattern.finditer(text))
        if len(sections) > 1: raise ValueError('CONFIG_UNSUPPORTED: agents 表重复')
        if not sections:
            if 'agents' in data: raise ValueError('CONFIG_UNSUPPORTED: agents 使用非表头写法，未修改')
            if text and not text.endswith(('\n', '\r')): text += newline
            text += newline + '[agents]' + newline
            start = len(text); end = start
        else:
            start = sections[0].end()
            m = re.search(r'(?m)^\s*\[', text[start:]); end = start + m.start() if m else len(text)
        block = text[start:end]
        expected = dict(data.get('agents', {}))
        def set_field(block, key, value):
            pat = re.compile(r'(?m)^(\s*' + re.escape(key) + r'\s*=\s*)([^\r\n#]*?)(\s*(?:#.*)?)\r?$')
            matches = list(pat.finditer(block))
            if len(matches) > 1: raise ValueError('CONFIG_UNSUPPORTED: 字段重复')
            if matches:
                return pat.sub(lambda m: m.group(1) + value + m.group(3), block, count=1)
            if block and not block.endswith(('\n','\r')): block += newline
            return block + key + ' = ' + value + newline
        if not enabled:
            block = set_field(block, 'enabled', 'true'); expected['enabled'] = True
        # Keep an existing legacy alias as the single source of truth.
        if limit is None or limit < target:
            key = 'max_threads' if 'max_threads' in expected and 'max_concurrent_threads_per_session' not in expected else 'max_concurrent_threads_per_session'
            block = set_field(block, key, str(target)); expected[key] = target
            if 'max_threads' in expected and key != 'max_threads':
                block = set_field(block, 'max_threads', str(target)); expected['max_threads'] = target
        new = text[:start] + block + text[end:]
        desired = dict(data); desired['agents'] = expected
        encoded = (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + new.encode('utf-8')
        if parse(encoded) != desired: raise ValueError('CONFIG_UNSUPPORTED: 安全编辑验证失败，未修改')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.comic-agent-', dir=str(path.parent))
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(encoded); out.flush(); os.fsync(out.fileno())
            if path.exists(): os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
            if path.is_symlink() or (path.read_bytes() if path.exists() else b'') != raw:
                raise ValueError('CONFIG_CHANGED: 配置被其他进程修改，未覆盖')
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        _, _, after, enabled_after = inspect(path)
        report.update(status='CONFIG_UPDATED', configured_limit=after, enabled=enabled_after,
                      configuration_changed=True)
        return report
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        report.update(status='CONFIGURATION_ERROR', configuration_validated=False,
                      error=str(exc), next_action='检查配置或权限；按实际可用容量继续，不宣称配置生效')
        return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('check','ensure'))
    p.add_argument('--config',type=Path)
    a=p.parse_args(); result=ensure(a.config, write=a.action=='ensure')
    print(json.dumps(result,ensure_ascii=False));return int(result['status']=='CONFIGURATION_ERROR')

if __name__=='__main__':raise SystemExit(main())
