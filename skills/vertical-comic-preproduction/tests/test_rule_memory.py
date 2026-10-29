"""Portable rule routing and real gate integration in isolated synthetic workspaces."""
import _historical_fixture
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from codex_reference_contract import digest
from rule_memory import LOADING_POLICY, loading_selection, select, load_selected, application_errors, binding_errors, review_template, source_index, routing_session, trigger_review, trigger_review_errors, inspection_plan
from usage_config import read_config, memory_source, runtime_limits
from historical_engines.batch_workflow import build_plan
from staged_workflow import qa_errors
from _historical_fixture import evaluate
import test_staged_workflow as staged

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def library(root):
    root.mkdir(parents=True, exist_ok=True)
    body = root / 'rule.md'
    body.write_text('# SYNTHETIC universal support rule\n', encoding='utf-8', newline='\n')
    rule = {'id': 'UNIT-MEM', 'title': 'Synthetic portable rule', 'version': '1', 'status': 'active',
            'scope': 'cross_work', 'primary_stage': 'generation', 'stages': ['shot_design', 'generation', 'image_review'],
            'admission': {'portable': True, 'contains_story_facts': False, 'rationale': 'TEST production method only'},
            'trigger': {'any_tags': ['person_on_bed'], 'any_visual_terms': ['床上', '盖着被子']},
            'requirements': {s: {'checks': ['support'], 'artifacts': ['spatial_diagram'] if s != 'image_review' else [],
                                'prompt_constraints': s == 'generation'} for s in ['shot_design', 'generation', 'image_review']},
            'file': {'path': body.name, 'sha256': digest(body)}}
    (root / '记忆索引.json').write_text(json.dumps({'policy': 'triggered_rules_v1', 'rules': [rule]}), encoding='utf-8', newline='\n')
    return {'policy': 'triggered_rules_v1', 'root': str(root), 'index': '记忆索引.json'}


def applied(source, stage, panel, artifact_root):
    match = select(source, stage, panel)[0]
    rule = match['rule']
    diagram = artifact_root / 'station.svg'
    diagram.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>', encoding='utf-8', newline='\n')
    return {'memory_id': rule['id'], 'rule_version': rule['version'], 'rule_signature': match['rule_signature'],
            'rule_sha256': rule['file']['sha256'], 'decision': 'APPLIED', 'reviewer': 'SYNTHETIC TEST ONLY',
            'evidence': 'SYNTHETIC test evidence, not actual visual approval',
            'checks': {'support': {'status': 'PASS', 'evidence': 'SYNTHETIC test check'}},
            'artifacts': [{'kind': 'spatial_diagram', 'file': {'path': diagram.name, 'sha256': digest(diagram)},
                           'reviewed': True, 'evidence': 'SYNTHETIC diagram fixture'}],
            'prompt_constraints': ['SYNTHETIC support constraint'], 'image_sha256': 'synthetic-image-sha'}


class MemoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = library(self.root / 'library')
        self.panel = {'memory_tags': ['person_on_bed'], 'prompt': 'SYNTHETIC support constraint'}

    def index(self):
        return json.loads((self.root / 'library/记忆索引.json').read_text(encoding='utf-8-sig'))

    def save_index(self, data):
        (self.root / 'library/记忆索引.json').write_text(json.dumps(data), encoding='utf-8', newline='\n')

    def add_rule(self,rid,tag):
        index=self.index();rule=copy.deepcopy(index['rules'][0]);rule.update(id=rid,title='SYNTHETIC '+rid)
        rule['trigger']={'any_tags':[tag],'any_visual_terms':[]};index['rules'].append(rule);self.save_index(index)

    def enable_loading(self):
        data=self.index();data['loading_policy']=LOADING_POLICY
        for rule in data['rules']:
            rule['load_policy']='stage_baseline' if rule['id']=='UNIT-MEM' else 'on_match'
            rule['version']='2'
        self.save_index(data);self.source['loading_policy']=LOADING_POLICY

    def test_stage_preload_does_not_create_execution_or_qa_requirements(self):
        self.enable_loading();panel={'memory_tags':[]}
        selected=loading_selection(self.source,'generation')
        self.assertEqual(len(selected),1);self.assertEqual(selected[0]['read_reasons'],['stage_baseline'])
        bodies,_=load_selected(self.source,selected,{},'run','worker');self.assertIn('body',bodies[0])
        self.assertEqual(select(self.source,'generation',panel),[])
        self.assertEqual(trigger_review(self.source,'shot_design',panel)['matched_rules'],[])
        self.assertEqual(application_errors(self.source,'generation',panel,self.root),[])
        self.assertEqual(review_template(self.source,panel,'synthetic-image'),[])

    def test_stage_preload_filters_status_stage_and_conditional_rules(self):
        self.add_rule('CONDITIONAL','contact');self.enable_loading()
        self.assertEqual([m['rule']['id'] for m in loading_selection(self.source,'generation')],['UNIT-MEM'])
        self.assertEqual(loading_selection(self.source,'visual_assets'),[])
        for status in ('candidate','disabled'):
            data=self.index();data['rules'][0]['status']=status;self.save_index(data)
            self.assertEqual(loading_selection(self.source,'generation'),[])

    def test_stage_and_panel_load_share_cache_and_do_not_duplicate_baseline(self):
        self.add_rule('CONDITIONAL','contact');self.enable_loading()
        first,cache=load_selected(self.source,loading_selection(self.source,'shot_design'),{},'run','worker')
        self.assertIn('body',first[0]);panel={'memory_tags':['person_on_bed','contact']}
        selected=loading_selection(self.source,'generation',panel)
        self.assertEqual(len(selected),2);self.assertEqual(selected[0]['read_reasons'],['stage_baseline','matched_condition'])
        bodies,cache=load_selected(self.source,selected,cache,'run','worker')
        self.assertNotIn('body',bodies[0]);self.assertIn('body',bodies[1])
        last,_=load_selected(self.source,loading_selection(self.source,'image_review',panel),cache,'run','worker')
        self.assertTrue(all('body' not in b for b in last))

    def test_preload_body_is_revalidated_and_cache_does_not_hide_tampering(self):
        self.enable_loading();selected=loading_selection(self.source,'generation')
        _,cache=load_selected(self.source,selected,{},'run','worker')
        (self.root/'library/rule.md').write_text('SYNTHETIC changed without hash', encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError):load_selected(self.source,selected,cache,'run','worker')

    def test_loading_version_change_rereads_only_changed_rule_and_rejects_stale_selection(self):
        self.add_rule('CONDITIONAL','contact');self.enable_loading();panel={'memory_tags':['contact']}
        selected=loading_selection(self.source,'generation',panel)
        _,cache=load_selected(self.source,selected,{},'run','worker')
        data=self.index();data['rules'][0]['version']='3';self.save_index(data)
        with self.assertRaises(ValueError):load_selected(self.source,selected,cache,'run','worker')
        updated,_=load_selected(self.source,loading_selection(self.source,'generation',panel),cache,'run','worker')
        self.assertIn('body',updated[0]);self.assertNotIn('body',updated[1])

    def test_preload_cache_cannot_cross_agent_run_or_context_reset(self):
        self.enable_loading();selected=loading_selection(self.source,'generation')
        _,cache=load_selected(self.source,selected,{},'run','worker')
        for run,worker,reload in (('other','worker',False),('run','other',False),('run','worker',True)):
            result,_=load_selected(self.source,selected,cache,run,worker,reload)
            self.assertIn('body',result[0])

    def test_loading_contract_cannot_be_silently_added_removed_or_cache_bypassed(self):
        legacy=copy.deepcopy(self.source);self.enable_loading()
        with routing_session():
            source_index(self.source)
            with self.assertRaises(ValueError):source_index(legacy)
            downgraded=copy.deepcopy(self.source);downgraded['loading_policy']='unknown'
            with self.assertRaises(ValueError):source_index(downgraded)
        self.assertTrue(binding_errors({'memory_source':self.source},shots={'memory_source':legacy}))
        data=self.index();del data['loading_policy'];self.save_index(data)
        with self.assertRaises(ValueError):source_index(self.source)
        with self.assertRaises(ValueError):source_index(legacy)

    def test_loading_metadata_is_required_but_never_replaces_actual_trigger(self):
        self.enable_loading();original=self.index()
        for value in (None,'unknown',[],True):
            data=copy.deepcopy(original);data['rules'][0]['load_policy']=value;self.save_index(data)
            with self.assertRaises(ValueError):source_index(self.source)
        data=copy.deepcopy(original);del data['rules'][0]['load_policy'];self.save_index(data)
        with self.assertRaises(ValueError):source_index(self.source)
        data=copy.deepcopy(original);data['rules'][0]['trigger']={'any_tags':[],'any_visual_terms':[]};self.save_index(data)
        with self.assertRaises(ValueError):source_index(self.source)

    def test_legacy_library_preserves_trigger_only_loading(self):
        self.assertEqual(loading_selection(self.source,'generation'),[])
        self.assertEqual(loading_selection(self.source,'generation',{'memory_tags':[]}),[])
        matches=loading_selection(self.source,'generation',self.panel)
        self.assertEqual(len(matches),1);self.assertEqual(matches[0]['read_reasons'],['matched_condition'])
        upgraded={**self.source,'loading_policy':LOADING_POLICY}
        with self.assertRaises(ValueError):source_index(upgraded)

    def test_cli_stage_load_then_panel_load_reuses_actual_body_without_qa(self):
        self.enable_loading();cache=self.root/'runtime-cache.json'
        command=[sys.executable, '-X', 'utf8',str(SCRIPTS/'rule_memory.py'),'--root',self.source['root'],'--loading-policy',LOADING_POLICY,
                 '--stage','generation','--mode','load-stage','--cache',str(cache),'--run-id','run','--worker-id','worker']
        result=subprocess.run(command,capture_output=True,text=True, encoding='utf-8');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=json.loads(result.stdout);self.assertEqual(report['matched_for_execution'],[])
        self.assertIn('body',report['memories'][0]);panel=self.root/'panel.json';panel.write_text(json.dumps(self.panel), encoding='utf-8', newline='\n')
        command[command.index('load-stage')]='load';command+=['--panel',str(panel)]
        result=subprocess.run(command,capture_output=True,text=True, encoding='utf-8');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=json.loads(result.stdout);self.assertEqual(len(report['matched_for_execution']),1)
        self.assertNotIn('body',report['memories'][0]);self.assertEqual(report['status'],'LOADED_NOT_APPROVED')

    def test_cli_manifest_cannot_downgrade_frozen_loading_source(self):
        self.enable_loading();manifest=self.root/'manifest.json'
        frozen=copy.deepcopy(self.source);frozen['root']=str(self.root/'different')
        manifest.write_text(json.dumps({'memory_source':frozen,'panels':[{'panel_id':'P001',**self.panel}]}), encoding='utf-8', newline='\n')
        result=subprocess.run([sys.executable, '-X', 'utf8',str(SCRIPTS/'rule_memory.py'),'--root',self.source['root'],'--loading-policy',LOADING_POLICY,
            '--stage','generation','--mode','select','--manifest',str(manifest),'--panel-id','P001'],capture_output=True,text=True, encoding='utf-8')
        self.assertEqual(result.returncode,1);self.assertIn('冻结manifest',result.stdout)

    def test_cli_invalid_manifest_cannot_silently_become_stage_only_load(self):
        self.enable_loading();manifest=self.root/'empty.json';manifest.write_text('{}', encoding='utf-8', newline='\n');cache=self.root/'cache.json'
        result=subprocess.run([sys.executable, '-X', 'utf8',str(SCRIPTS/'rule_memory.py'),'--root',self.source['root'],'--loading-policy',LOADING_POLICY,
            '--stage','generation','--mode','load','--manifest',str(manifest),'--panel-id','P001','--cache',str(cache),
            '--run-id','run','--worker-id','worker'],capture_output=True,text=True, encoding='utf-8')
        self.assertEqual(result.returncode,1);self.assertFalse(cache.exists());self.assertEqual(manifest.read_text(encoding='utf-8-sig'),'{}')

    def test_visible_subjects_cannot_lose_continuity_by_missing_tag(self):
        self.add_rule('MEM-005','visual_subjects_present')
        for visible in ({'characters_visible':['A']},{'scene_binding':{'background_visible':True}},
                        {'background_anchors_visible':['window']},{'props_visible':['cup']}):
            panel={'memory_tags':[],**visible};matches=select(self.source,'shot_design',panel)
            self.assertIn('MEM-005',[m['rule']['id'] for m in matches]);self.assertTrue(application_errors(self.source,'shot_design',panel,self.root))
        self.assertEqual(select(self.source,'shot_design',{'memory_tags':[],'locked_script':{'dialogue':'window'}}),[])

    def test_human_applicability_is_explicit_not_inferred_from_character_id(self):
        self.add_rule('MEM-006','human_figure_visible');panel={'memory_tags':[],'characters_visible':['A']}
        review=trigger_review(self.source,'shot_design',panel)
        self.assertEqual(review['human_figure_visible']['decision'],'UNREVIEWED');self.assertEqual(review['matched_rules'],[])
        self.assertTrue(trigger_review_errors(self.source,'shot_design',panel,review))
        self.assertTrue(trigger_review_errors(self.source,'shot_design',panel,None))
        review['human_figure_visible']={'decision':'APPLIES','evidence':'SYNTHETIC human forearm visible'}
        self.assertTrue(trigger_review_errors(self.source,'shot_design',panel,review))
        panel['memory_tags']=['human_figure_visible'];review.update(trigger_review(self.source,'shot_design',panel));review['human_figure_visible']={'decision':'APPLIES','evidence':'SYNTHETIC forearm and hand'}
        self.assertEqual(trigger_review_errors(self.source,'shot_design',panel,review),[])
        animal={'memory_tags':[],'characters_visible':['APPROVED_ANIMAL']};review=trigger_review(self.source,'shot_design',animal)
        review['human_figure_visible']={'decision':'NOT_APPLICABLE','evidence':'SYNTHETIC approved quadruped, no human parts'}
        self.assertEqual(trigger_review_errors(self.source,'shot_design',animal,review),[])

    def test_routing_cache_reuses_matching_but_not_changed_verdicts(self):
        app=applied(self.source,'generation',self.panel,self.root)
        with routing_session() as memo:
            self.assertEqual(application_errors(self.source,'generation',self.panel,self.root,[app]),[])
            app['checks']['support']['status']='FAIL'
            self.assertTrue(application_errors(self.source,'generation',self.panel,self.root,[app]))
            self.assertEqual(memo['index_parses'],1);self.assertGreater(memo['selection_hits'],0)

    def test_routing_cache_invalidates_changed_index_body_and_panel(self):
        with routing_session() as memo:
            old=select(self.source,'generation',self.panel)[0]['rule_signature']
            self.assertEqual(select(self.source,'generation',{'memory_tags':[]}),[])
            index=self.index();index['rules'][0]['version']='2';self.save_index(index)
            match=select(self.source,'generation',self.panel)[0]
            self.assertNotEqual(old,match['rule_signature']);self.assertEqual(memo['index_parses'],2)
            app=applied(self.source,'generation',self.panel,self.root)
            (self.root/'library/rule.md').write_text('SYNTHETIC tampered body', encoding='utf-8', newline='\n')
            self.assertTrue(application_errors(self.source,'generation',self.panel,self.root,[app]))

    def test_cached_index_and_match_cannot_be_mutated_by_a_caller(self):
        with routing_session():
            _,index=source_index(self.source);index['rules'][0]['version']='poisoned'
            first=select(self.source,'generation',self.panel);first[0]['rule']['version']='poisoned'
            self.assertEqual(select(self.source,'generation',self.panel)[0]['rule']['version'],'1')

    def test_routing_cache_does_not_survive_next_gate(self):
        with routing_session() as first:select(self.source,'generation',self.panel)
        with routing_session() as second:select(self.source,'generation',self.panel)
        self.assertIsNot(first,second);self.assertEqual(first['index_parses'],1);self.assertEqual(second['index_parses'],1)

    def test_inspection_plan_keeps_every_rule_check_separate_and_unreviewed(self):
        panel={'panel_id':'P001'};item={'image_sha256':'image','dimension_review':{'identity':{'status':'UNREVIEWED'}},
            'style_review':{'status':'UNREVIEWED'},'memory_review':[{'memory_id':'MEM-005','rule_signature':'version',
            'checks':{'character_consistency':{'status':'UNREVIEWED'},'key_prop_continuity':{'status':'UNREVIEWED'}}}]}
        original=copy.deepcopy(item);plan=inspection_plan(panel,item,'manifest')
        targets=[t for g in plan['groups'] for t in g['targets']]
        self.assertEqual(len([t for t in targets if t['record']=='memory_review']),2)
        self.assertEqual(plan['status'],'UNREVIEWED');self.assertEqual(item,original)

    def test_dialogue_is_excluded_but_visual_event_recalls(self):
        panel = {'memory_tags': [], 'locked_script': {'dialogue': '床上', 'inner_voice': '床上'}}
        self.assertEqual(select(self.source, 'generation', panel), [])
        panel['locked_script']['event_text'] = '床上'
        self.assertEqual(len(select(self.source, 'generation', panel)), 1)

    def test_no_hit_never_reads_body(self):
        with patch('rule_memory.checked_file', side_effect=AssertionError('must not read body')):
            result, _ = load_selected(self.source, select(self.source, 'generation', {'memory_tags': []}), {}, 'run', 'worker')
        self.assertEqual(result, [])

    def test_stage_and_candidate_excluded(self):
        self.assertEqual(select(self.source, 'visual_assets', self.panel), [])
        data = self.index(); data['rules'][0]['status'] = 'candidate'; self.save_index(data)
        self.assertEqual(select(self.source, 'generation', self.panel), [])

    def test_enabled_memory_requires_semantic_classification(self):
        with self.assertRaises(ValueError): select(self.source, 'generation', {})

    def test_body_cache_is_scoped_to_run_worker_and_version(self):
        matches = select(self.source, 'generation', self.panel)
        first, cache = load_selected(self.source, matches, {}, 'r', 'w')
        self.assertIn('body', first[0])
        same, _ = load_selected(self.source, matches, cache, 'r', 'w')
        self.assertNotIn('body', same[0])
        for run, worker in [('new', 'w'), ('r', 'new')]:
            other, _ = load_selected(self.source, matches, cache, run, worker)
            self.assertIn('body', other[0])
        reread, _ = load_selected(self.source, matches, cache, 'r', 'w', True)
        self.assertIn('body', reread[0])
        data = self.index(); data['rules'][0]['version'] = '2'; self.save_index(data)
        updated, _ = load_selected(self.source, select(self.source, 'generation', self.panel), cache, 'r', 'w')
        self.assertIn('body', updated[0])

    def test_approved_checks_and_diagram_are_required(self):
        app = applied(self.source, 'generation', self.panel, self.root)
        self.assertEqual(application_errors(self.source, 'generation', self.panel, self.root, [app]), [])
        app['artifacts'] = []
        self.assertIn('spatial_diagram', ' '.join(application_errors(self.source, 'generation', self.panel, self.root, [app])))

    def test_bad_svg_is_hold_not_uncaught_error(self):
        app = applied(self.source, 'generation', self.panel, self.root)
        (self.root / 'station.svg').write_text('not SVG', encoding='utf-8', newline='\n')
        app['artifacts'][0]['file']['sha256'] = digest(self.root / 'station.svg')
        self.assertTrue(application_errors(self.source, 'generation', self.panel, self.root, [app]))

    def test_prompt_constraint_must_reach_actual_prompt(self):
        app = applied(self.source, 'generation', self.panel, self.root)
        self.panel['prompt'] = 'omitted'
        self.assertTrue(application_errors(self.source, 'generation', self.panel, self.root, [app]))

    def test_keyword_false_positive_can_be_excluded_but_tag_cannot(self):
        panel = {'memory_tags': [], 'locked_script': {'event_text': '人物在地面盖着被子'}}
        app = applied(self.source, 'generation', panel, self.root)
        app.update(decision='NOT_APPLICABLE', reason='Ground bedding; no bed in this shot')
        self.assertEqual(application_errors(self.source, 'generation', panel, self.root, [app]), [])
        panel['memory_tags'] = ['person_on_bed']
        self.assertTrue(application_errors(self.source, 'generation', panel, self.root, [app]))

    def test_image_review_requires_current_output_hash_and_never_auto_passes(self):
        templ = review_template(self.source, self.panel, 'actual-output')
        self.assertEqual(templ[0]['decision'], 'UNREVIEWED')
        app = applied(self.source, 'image_review', self.panel, self.root)
        self.assertTrue(application_errors(self.source, 'image_review', self.panel, self.root, [app], 'different'))
        self.assertEqual(application_errors(self.source, 'image_review', self.panel, self.root, [app], 'synthetic-image-sha'), [])

    def test_index_metadata_change_invalidates_execution(self):
        app = applied(self.source, 'generation', self.panel, self.root)
        data = self.index(); data['rules'][0]['requirements']['generation']['checks'].append('new_check'); self.save_index(data)
        self.assertIn('规则版本变更', ' '.join(application_errors(self.source, 'generation', self.panel, self.root, [app])))

    def test_body_tamper_is_detected_even_with_cached_body(self):
        matches = select(self.source, 'generation', self.panel)
        _, cache = load_selected(self.source, matches, {}, 'r', 'w')
        (self.root / 'library/rule.md').write_text('changed without hash update', encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError): load_selected(self.source, matches, cache, 'r', 'w')

    def test_nonportable_and_escaping_records_rejected(self):
        original = self.index()
        for update in [{'scope': 'episode'}, {'episode_id': 'E001'}, {'file': {'path': '../escape.md', 'sha256': '0'*64}}]:
            data = copy.deepcopy(original); data['rules'][0].update(update); self.save_index(data)
            with self.assertRaises(ValueError): source_index(self.source)

    def test_source_removal_cannot_bypass_binding(self):
        self.assertTrue(binding_errors({'memory_source': self.source}, shots={}, packet={}))
        self.assertEqual(binding_errors({}, {}, {}), [])

    def test_repair_operation_automatically_activates_rule(self):
        data = self.index(); data['rules'][0]['trigger'] = {'any_tags': ['image_repair'], 'any_visual_terms': []}; self.save_index(data)
        self.assertEqual(len(select(self.source, 'generation', {'memory_tags': [], 'operation': 'repair'})), 1)

    def test_cli_cannot_overwrite_panel_with_cache(self):
        panel = self.root / 'panel.json'; panel.write_text(json.dumps(self.panel), encoding='utf-8', newline='\n'); before = panel.read_bytes()
        result = subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPTS/'rule_memory.py'), '--root', self.source['root'], '--mode', 'load', '--stage', 'generation', '--panel', str(panel), '--cache', str(panel), '--run-id', 'run', '--worker-id', 'worker'], capture_output=True)
        self.assertEqual(result.returncode, 1); self.assertEqual(panel.read_bytes(), before)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        library(self.root/'library'); (self.root/'script.xlsx').write_bytes(b'SYNTHETIC fixture')
        (self.root/'assets').mkdir()
        self.config = {'policy':'comic_usage_v1', 'production':{'book':'UNIT', 'episodes':['E001','E002','E003','E004','E005']},
                       'inputs':{'script_path':str(self.root/'script.xlsx'), 'asset_root':str(self.root/'assets'), 'memory_root':str(self.root/'library')},
                       'generation':{'episode_workers':5,'max_inflight_images':5,'batch_size':5},
                       'memory':{'index':'记忆索引.json','cache':'run_worker_version','admission':'cross_work_only'}}
        self.path = self.root/'config.json'; self.save()

    def save(self): self.path.write_text(json.dumps(self.config), encoding='utf-8', newline='\n')

    def enable_loading(self):
        index_path=self.root/'library/记忆索引.json';data=json.loads(index_path.read_text(encoding='utf-8-sig'));data['loading_policy']=LOADING_POLICY
        for rule in data['rules']:rule['load_policy']='stage_baseline'
        index_path.write_text(json.dumps(data), encoding='utf-8', newline='\n');self.config['memory']['loading_policy']=LOADING_POLICY;self.save()

    def test_config_loading_contract_must_match_library_explicitly(self):
        self.enable_loading();self.assertEqual(memory_source(read_config(self.path))['loading_policy'],LOADING_POLICY)
        for value in ('unknown',None,False):
            self.config['memory']['loading_policy']=value;self.save()
            with self.assertRaises(ValueError):read_config(self.path)
        del self.config['memory']['loading_policy'];self.save()
        with self.assertRaises(ValueError):read_config(self.path)

    def test_new_init_binds_loading_contract_without_resetting_config_root_override(self):
        self.enable_loading();out=self.root/'new'
        command=[sys.executable, '-X', 'utf8',str(SCRIPTS/'init_preproduction.py'),'--config',str(self.path),'--memory-root',str(self.root/'library'),
                 '--memory-loading-policy',LOADING_POLICY,'--output',str(out),'--book','UNIT','--episode','E001']
        result=subprocess.run(command,capture_output=True,text=True, encoding='utf-8');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        state=json.loads((out/'00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(state['memory_source'],memory_source(read_config(self.path)));self.assertEqual(state['gates'],{})
        for filename in ('00_输入审计/本话配置.json','01_镜头改编_CANDIDATE/镜头改编表.json','04_B提示词包_CANDIDATE/全话提示词索引.json'):
            self.assertEqual(json.loads((out/filename).read_text(encoding='utf-8-sig'))['memory_source'],state['memory_source'])
        self.assertFalse(list(out.rglob('*cache*')));self.assertEqual(state['production_authorization'],None)

    def test_direct_init_requires_explicit_new_loading_contract_before_writes(self):
        self.enable_loading();out=self.root/'direct'
        command=[sys.executable, '-X', 'utf8',str(SCRIPTS/'init_preproduction.py'),'--memory-root',str(self.root/'library'),
                 '--output',str(out),'--book','UNIT','--episode','E001']
        result=subprocess.run(command,capture_output=True);self.assertNotEqual(result.returncode,0);self.assertFalse(out.exists())
        result=subprocess.run(command+['--memory-loading-policy',LOADING_POLICY],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads((out/'00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'));self.assertEqual(state['memory_source']['loading_policy'],LOADING_POLICY)

    def test_capacity_counters_are_independent_and_runtime_capped(self):
        config = read_config(self.path)
        self.assertEqual(runtime_limits(config,4,5)['worker_agents'],3)
        self.assertEqual(runtime_limits(config,6,2)['max_inflight'],2)
        self.assertEqual(runtime_limits(config,6)['max_inflight'],1)
        self.assertEqual(runtime_limits(config,1,5)['worker_agents'],0)
        self.assertEqual(runtime_limits(config,6,5)['worker_agents'],5)

    def test_invalid_paths_limits_and_memory_policy_fail(self):
        original = copy.deepcopy(self.config)
        changes=[('inputs','script_path','missing'),('generation','episode_workers',True),('generation','batch_size',6),('memory','admission','all_events')]
        for section,key,value in changes:
            self.config=copy.deepcopy(original); self.config[section][key]=value; self.save()
            with self.assertRaises(ValueError): read_config(self.path)

    def test_init_binds_sources_without_approving_or_overwriting(self):
        output=self.root/'out'
        command=[sys.executable, '-X', 'utf8',str(SCRIPTS/'init_preproduction.py'),'--config',str(self.path),'--output',str(output),'--book','UNIT','--episode','E001']
        result=subprocess.run(command,capture_output=True); self.assertEqual(result.returncode,0,result.stderr)
        state_path=output/'00_输入审计/生产流程.json'; state=json.loads(state_path.read_text(encoding='utf-8-sig'))
        self.assertEqual(state['execution_mode'],'episode_async_v1');self.assertNotIn('batch_size',state); self.assertEqual(state['gates'],{})
        for path in ['01_镜头改编_CANDIDATE/镜头改编表.json','04_B提示词包_CANDIDATE/全话提示词索引.json']:
            self.assertEqual(json.loads((output/path).read_text(encoding='utf-8-sig'))['memory_source'],state['memory_source'])
        before=state_path.read_bytes(); subprocess.run(command,check=True,capture_output=True); self.assertEqual(state_path.read_bytes(),before)

    def test_smaller_batch_still_preserves_first_five_boundary(self):
        ids=[f'P{i:03d}' for i in range(1,9)]
        state={'batch_size':3,'panels':[{'panel_id':p} for p in ids], 'source_snapshot':{}, 'visual_basis':{}, 'shot_manifest':{}}
        shots={'panels':[{'panel_id':p,'generation_dependencies':[],'requires_state_review':False,'visual_state_keys':['s']} for p in ids]}
        plan=build_plan(state,shots)
        self.assertEqual(plan['pilot_panel_ids'],ids[:5])
        self.assertEqual([len(b['panel_ids']) for b in plan['batches']],[3,2,3])


class MemoryGateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.h=staged.StagedTests('test_actual_style_input_is_exported'); self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.root=self.h.root; self.source=library(self.root/'library')
        self.h.panel['memory_tags']=['person_on_bed']
        self.h.manifest['memory_source']=self.source
        self.state=self.h.real_input(); self.state['memory_source']=self.source
        self.panel=self.h.panel
        self.panel['prompt']+='\nSYNTHETIC support constraint'
        self.panel['memory_applications']={'generation':[applied(self.source,'generation',self.panel,self.root)]}
        self.h.shots[0]['memory_applications']={'shot_design':[applied(self.source,'shot_design',self.panel,self.root)]}
        self.sync()

    def sync(self):
        (self.root/'P001/prompt.txt').write_text(self.panel['prompt'], encoding='utf-8', newline='\n')
        self.h.f.write('P001/提示词.json',self.panel)
        shots={**self.h.manifest,'panels':self.h.shots}
        self.state['shot_manifest']=self.h.f.write('shots.json',shots)
        self.state['gates']['shot_design']=self.h.approve([self.state['visual_basis'],self.state['shot_manifest']])
        record=self.state['panels'][0]
        record['package_manifest']=self.h.f.write('全话提示词索引.json',self.h.manifest)
        record['shot_subset']=self.h.f.write('shot-subset.json',shots)

    def test_actual_preflight_requires_both_stage_records(self):
        result=evaluate(self.state,self.root,'generate','P001'); self.assertEqual(result['status'],'PASS',result)
        self.panel['memory_applications']['generation'][0]['artifacts']=[]; self.sync()
        result=evaluate(self.state,self.root,'generate','P001'); self.assertEqual(result['status'],'HOLD',result)
        self.assertIn('spatial_diagram',' '.join(result['errors']))

    def test_loading_extension_keeps_actual_full_preflight_and_stage_checks(self):
        index_path=self.root/'library/记忆索引.json';data=json.loads(index_path.read_text(encoding='utf-8-sig'))
        data['loading_policy']=LOADING_POLICY;data['rules'][0].update(load_policy='stage_baseline',version='2')
        index_path.write_text(json.dumps(data), encoding='utf-8', newline='\n');self.source['loading_policy']=LOADING_POLICY
        self.panel['memory_applications']['generation']=[applied(self.source,'generation',self.panel,self.root)]
        self.h.shots[0]['memory_applications']['shot_design']=[applied(self.source,'shot_design',self.panel,self.root)];self.sync()
        _,cache=load_selected(self.source,loading_selection(self.source,'generation'),{},'run','worker')
        result=evaluate(self.state,self.root,'generate','P001');self.assertEqual(result['status'],'PASS',result)
        self.panel['memory_applications']['generation'][0]['checks']['support']['status']='FAIL';self.sync()
        result=evaluate(self.state,self.root,'generate','P001');self.assertEqual(result['status'],'HOLD',result)
        self.assertIn('未实际核对',' '.join(result['errors']));self.assertTrue(cache['loaded'])

    def test_batch_preflight_and_source_binding_cannot_bypass(self):
        self.state['execution_mode']='batch5_v1'; self.h.manifest['execution_mode']='batch5_v1'
        for p in [self.panel,*self.h.shots]: p.update(generation_dependencies=[],requires_state_review=False)
        self.sync(); shots=json.loads((self.root/'shots.json').read_text(encoding='utf-8-sig'))
        self.state['batch_plan']=self.h.f.write('plan.json',build_plan(self.state,shots))
        result=evaluate(self.state,self.root,'generate','P001'); self.assertEqual(result['status'],'PASS',result)
        self.h.manifest.pop('memory_source'); self.sync()
        self.state['batch_plan']=self.h.f.write('plan.json',build_plan(self.state,json.loads((self.root/'shots.json').read_text(encoding='utf-8-sig'))))
        self.assertEqual(evaluate(self.state,self.root,'generate','P001')['status'],'HOLD')

    def test_qa_scaffold_outputs_hash_bound_unreviewed_memory(self):
        report,_=self.h.f.qa_report()
        item=report['panels'][0]; memory=item['memory_review'][0]
        self.assertEqual(memory['decision'],'UNREVIEWED'); self.assertEqual(memory['image_sha256'],item['image_sha256'])
        self.assertTrue(application_errors(self.source,'image_review',self.panel,self.root,item['memory_review'],item['image_sha256']))


    def test_real_returned_image_qa_blocks_until_memory_review_is_complete(self):
        from PIL import Image
        from codex_reference_contract import validate_panel
        _, plan = validate_panel(self.panel, self.root)
        output = self.root/'synthetic-output.png'
        Image.new('RGB',(90,160),'white').save(output)
        req = {'attempt_id':'UNIT_ONLY','backend_id':'codex_builtin_imagegen','panel_id':'P001',**plan,
               'source_kind':'observed_tool_call','source_locator':'synthetic-unittest://not-real'}
        res = {'attempt_id':'UNIT_ONLY','status':'COMPLETED','outputs':[{'path':output.name,'sha256':digest(output)}],
               'source_kind':'observed_tool_result','source_locator':'synthetic-unittest://not-real'}
        self.panel['generation_execution']={'status':'COMPLETED','attempt_id':'UNIT_ONLY',
            'request_evidence':self.h.f.write('request.json',req),'response_evidence':self.h.f.write('response.json',res)}
        report,_=self.h.f.qa_report()
        self.assertEqual(report['errors'],[])
        item=report['panels'][0]
        for review in [*item['dimension_review'].values(),item['style_review']]:
            review.update(status='PASS',reviewer='SYNTHETIC',evidence='TEST ONLY')
        for key in ('camera_match','shot_scale_match','background_view_match','body_crop_match','required_visible_information_preserved','no_extra_offscreen_characters'):
            item[key]=True
        record=self.state['panels'][0]
        record.update(status='VISUAL_PASS',package_manifest={'path':'全话提示词索引.json','sha256':digest(self.root/'全话提示词索引.json')},
                      output={'path':output.name,'sha256':digest(output)},qa_report=self.h.f.write('qa.json',report))
        self.assertIn('MEMORY_HOLD',' '.join(qa_errors(self.root,record)))
        app=applied(self.source,'image_review',self.panel,self.root); app['image_sha256']=digest(output)
        item['memory_review']=[app]; record['qa_report']=self.h.f.write('qa.json',report)
        self.assertEqual(qa_errors(self.root,record),[])
        item['memory_review'][0]['image_sha256']='stale'; record['qa_report']=self.h.f.write('qa.json',report)
        self.assertIn('MEMORY_HOLD',' '.join(qa_errors(self.root,record)))


if __name__=='__main__': unittest.main()
