"""Read an XLSX as raw cell evidence, without interpreting panel IDs or approving it."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
from platform_io import configure_stdio, atomic_json


CACHE_SCHEMA = 'raw_workbook_snapshot_cache_v1'


def _payload_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def snapshot(path, cache_root=None, *, metrics=None):
    """Read immutable raw evidence; optional cache is content/parser/schema bound.

    Returned dictionaries are fresh values. Cache metadata never grants semantic
    approval; corrupt/incompatible entries are reparsed from the current source.
    """
    from openpyxl import load_workbook, __version__ as parser_version
    path = Path(path).resolve()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    parser = 'openpyxl/' + parser_version + '/read_only/data_only=false'
    cache_key = _payload_hash([before, parser, CACHE_SCHEMA])
    cache_path = Path(cache_root) / 'raw-workbooks' / ('raw-workbook-' + cache_key + '.json') if cache_root is not None else None
    if cache_path and cache_path.is_file():
        try:
            entry = json.loads(cache_path.read_text(encoding='utf-8-sig'))
            result = entry['snapshot']
            payload = {k: v for k, v in result.items() if k != 'payload_sha256'}
            if (entry.get('schema') != CACHE_SCHEMA or entry.get('parser') != parser
                    or result.get('source_sha256') != before
                    or result.get('payload_sha256') != _payload_hash(payload)):
                raise ValueError('invalid raw workbook cache')
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        else:
            if hashlib.sha256(path.read_bytes()).hexdigest() != before:
                raise ValueError('源工作簿读取期间变化，请重新读取')
            if metrics is not None:metrics['raw_snapshot_cache_reuses']=metrics.get('raw_snapshot_cache_reuses',0)+1
            return result
    if metrics is not None:metrics['raw_workbook_parses']=metrics.get('raw_workbook_parses',0)+1
    sheets = []
    # Explicit binary stream guarantees closure on Windows, including read errors.
    with path.open('rb') as stream:
        book = load_workbook(stream, read_only=True, data_only=False)
        try:
            for sheet in book:
                rows = []
                for row in sheet.iter_rows():
                    cells = []
                    for cell in row:
                        if cell.value is None:
                            continue
                        value = cell.value
                        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
                            value = value.isoformat()
                        cells.append({'coordinate': cell.coordinate, 'type': cell.data_type, 'value': value})
                    if cells:
                        rows.append(cells)
                sheets.append({'name': sheet.title, 'rows': rows})
        finally:
            book.close()
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise ValueError('源工作簿读取期间变化，请重新读取')
    result = {'policy': 'raw_workbook_evidence_v1', 'source_sha256': before,
              'sheets': sheets, 'status': 'RAW_EVIDENCE_NOT_SEMANTIC_APPROVAL'}
    result['payload_sha256'] = _payload_hash(result)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(cache_path, {'schema': CACHE_SCHEMA, 'parser': parser, 'snapshot': result})
    return result


if __name__ == '__main__':
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cache-root', type=Path)
    args = parser.parse_args()
    result = snapshot(args.source, cache_root=args.cache_root)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'output': str(args.output.resolve())}, ensure_ascii=False))
