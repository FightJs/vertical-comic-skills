"""Versioned handoff scope. Old receipts and input digests keep their meaning."""

LEGACY_POLICY = 'rehearsed_zip_handoff_v1'
EPISODE_POLICY = 'rehearsed_zip_handoff_v2'
EPISODE_WINDOW = 'full_episode_v1'


def episode_mode(index):
    policy = index.get('policy')
    window = index.get('production_window_policy')
    if policy == EPISODE_POLICY:
        if window != EPISODE_WINDOW:
            raise ValueError('整话交接须声明full_episode_v1，不能推测或降级窗口')
        return True
    if policy != LEGACY_POLICY or window not in (None, 'reviewed_halves_v1'):
        raise ValueError('未知交接格式或生产窗口，不能重解释旧批准')
    return False


def validate_episode(index, episode):
    ids = episode['panel_ids']
    if episode_mode(index):
        if 'halves' in episode:
            raise ValueError('新版整话交接不能混入halves')
        kinds = {'READY', 'WAIT_DEPENDENCY', 'HOLD', 'REUSE'}
    else:
        cut = (len(ids) + 1) // 2
        if episode.get('halves') != {'H001': ids[:cut], 'H002': ids[cut:]}:
            raise ValueError(episode['episode_id'] + ':半话不符合准确源序ceil(N/2)')
        kinds = {'READY_H001', 'PREPARED_H002', 'WAIT_DEPENDENCY', 'HOLD', 'REUSE'}
    for row in episode.get('panels', []):
        if row.get('classification') not in kinds:
            raise ValueError(str(row.get('panel_id')) + ':未知或混合版本交接状态')


def ready_ids(index, episode):
    kind = 'READY' if episode_mode(index) else 'READY_H001'
    return [row['panel_id'] for row in episode['panels'] if row['classification'] == kind]


def ready_key(index):
    return 'ready_panel_ids' if episode_mode(index) else 'ready_h001'


def count_key(index):
    return 'ready_panel_count' if episode_mode(index) else 'ready_h001_count'
