"""Synthetic approved-context workloads; never production approval evidence."""
import copy
import hashlib
import json
from pathlib import Path


def write(root, name, value):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def contexts(root, count=35):
    root = Path(root)
    sources, all_entries, packets = [], [], []
    episodes = [f'E{i:03}' for i in range((count + 34) // 35)]
    remaining = count
    for index, episode in enumerate(episodes):
        size = min(35, remaining)
        remaining -= size
        ids = [f'P{i:03}' for i in range(1, size + 1)]
        source = write(root, episode+'/source.json', {'synthetic': True})
        snap = write(root, episode+'/snapshot.json', {'source_sha256': source['sha256'],
                     'panel_ids': ids, 'locked_scripts': {pid: 'SYNTHETIC '+pid for pid in ids}})
        basis = write(root, episode+'/basis.json', {'book_id': 'BENCH', 'episode_id': episode})
        rows = [{'panel_id': pid, 'locked_script': 'SYNTHETIC '+pid,
                 'details': [{'actor': 'A', 'constraints': ['pose', 'scene', 'identity'] * 5} for _ in range(8)]}
                for pid in ids]
        shots = {'book_id': 'BENCH', 'episode_id': episode, 'readiness_policy': 'panel_readiness_v1', 'panels': rows}
        old = write(root, episode+'/old-shots.json', shots)
        revised = copy.deepcopy(shots)
        for row in revised['panels']:row['inspection_plan'] = {'observation': 'SYNTHETIC observation only'}
        new = write(root, episode+'/new-shots.json', revised)
        proof = {'status': 'APPROVED', 'source_kind': 'user_message', 'quote': 'SYNTHETIC TEST ONLY',
                 'source_locator': 'synthetic://test', 'book_id': 'BENCH', 'episode_id': episode,
                 'panel_ids': ids, 'artifacts': [basis, old, source, snap]}
        sources.append({'root': str(root.resolve()), 'episode_id': episode, 'source_script': source,
                        'source_snapshot': snap, 'visual_basis': basis, 'shot_manifest': new,
                        'visual_approval': proof, 'shot_approval': proof})
        for row in rows:
            pid = row['panel_id']
            packet = {'book_id': 'BENCH', 'episode_id': episode, 'panels': [row]}
            if all_entries:
                used = sorted({e['source'] for e in all_entries})
                # Source indices are sequential, including the current episode
                # only after its first panel has entered the preceding scope.
                context = {'policy': 'approved_shot_context_v1', 'book_id': 'BENCH',
                           'current': {'episode_id': episode, 'panel_id': pid}, 'episode_order': episodes,
                           'sources': sources[:max(used)+1], 'entries': list(all_entries)}
                packet['continuity_context'] = write(root, episode+'/'+pid+'-context.json', context)
            packets.append(packet)
            all_entries.append({'source': index, 'panel_id': pid})
    return packets
