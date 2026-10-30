"""Current production rejects blank scenes while old evidence remains reproducible."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from visual_evidence import (BACKGROUND_POLICY,LEGACY_BACKGROUND_POLICY,production_background_errors,
    execution_block,packet_errors,background_config_errors)
from test_background_policy import background_fixture,recompile

class SceneBackgroundTests(unittest.TestCase):
    def test_new_flat_cannot_compile_even_with_no_optional_decorations(self):
        b,p=background_fixture();p['framing']['background_treatment']='scene_flat'
        p['framing']['background_plan']['retain']=[]
        with self.assertRaisesRegex(ValueError,'SCENE_BACKGROUND_REQUIRED'):execution_block(p)

    def test_old_flat_evidence_is_readable_but_not_dispatchable(self):
        b,p=background_fixture();b['background_policy']=p['background_policy']=LEGACY_BACKGROUND_POLICY
        p['framing']['background_treatment']='scene_flat';p['framing']['background_plan']['retain']=[]
        recompile(b,p)
        self.assertIn('人物身后完整使用同色实色底',p['prompt'])
        self.assertEqual(packet_errors(b,p,p,b),[])
        self.assertTrue(production_background_errors(p))

    def test_softened_and_outline_keep_scene_and_do_not_force_offscreen_furniture(self):
        for mode in ('clear_limited','scene_softened','scene_outline'):
            b,p=background_fixture(mode)
            self.assertEqual(production_background_errors(p),[])
            self.assertIn('本机位可见',p['prompt'])
            self.assertIn('不得扩大取景或添加画外家具',p['prompt'])

    def test_explicit_blank_text_blocked_even_under_other_mode(self):
        for text in ('背景完全留白','人物身后完整使用同色实色底','删除全部背景','背景为纯色','背景纯白色','plain white background'):
            with self.subTest(text=text):self.assertTrue(production_background_errors({},text))
        for text in ('禁止背景完全留白','背景不抹成纯色或无结构渐变','不要删除全部背景','no plain white background','省略墙面纹理，保留门框','背景为纯白墙面，门框可见'):
            with self.subTest(text=text):self.assertEqual(production_background_errors({},text),[])
        self.assertTrue(production_background_errors({},'背景完全留白，人物不要模糊'))

    def test_cached_legacy_job_cannot_claim_or_mutate_state(self):
        from runtime_pipeline import claim_and_register
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'生产流程.json';p.write_text('{}');before=p.read_bytes()
            cached={'packet':{'panels':[{'framing':{'background_treatment':'scene_flat'}}]},'arguments':{'prompt':'legacy flat'}}
            with patch('prepared_job_store.store',return_value=Mock(get=Mock(return_value=cached))):
                with self.assertRaisesRegex(ValueError,'SCENE_BACKGROUND_REQUIRED'):claim_and_register(p,{})
            self.assertEqual(p.read_bytes(),before)

    def test_one_quick_observation_can_record_severe_blank_as_repairable(self):
        from light_review import review_errors,repair_eligible,REPAIR_POLICY
        issue={'story_critical':True,'story_impact':'scene_background_missing','location':'background',
               'problem':'observed full solid background with no scene structure','target':'retain visible scene geometry'}
        row={'light_review':{'policy':'light_story_review_v1','repair_threshold_policy':REPAIR_POLICY,
            'status':'FAIL','reviewer':'synthetic','single_observation':'Scene structure absent; identity and action visible','issues':[issue]}}
        self.assertEqual(review_errors(row),[]);self.assertTrue(repair_eligible(issue,True))
        row['light_review']['status']='PASS';self.assertTrue(review_errors(row))
        issue['story_critical']=False;self.assertTrue(review_errors(row))

    def test_expired_review_does_not_auto_adopt_severe_blank(self):
        from light_review import prepare_observations,REPAIR_POLICY
        item={'light_review':{'policy':'light_story_review_v1','repair_threshold_policy':REPAIR_POLICY}}
        proposal={'reviewer':'synthetic','verdict':'FAIL','reason':'one observed scene failure',
            'light_observations':{'single_observation':'background is a flat blank field','issues':[
                {'story_impact':'scene_background_missing','location':'background','problem':'no scene structure','target':'visible room contours'}]}}
        prepare_observations(item,proposal,{'round_id':1},allow_manual_critical=True)
        self.assertFalse(proposal['adopt'])
        self.assertEqual(item['light_review']['status'],'FAIL')

    def test_delivery_selection_rejects_severe_blank_even_if_marked_adopted(self):
        from production_decisions import selected
        item={'light_review':{'issues':[{'story_impact':'scene_background_missing'}]}}
        with patch('production_decisions.load_decision',return_value=({}, {},item,{})):
            with self.assertRaisesRegex(ValueError,'SCENE_BACKGROUND_REQUIRED'):
                selected(Path('.'),{'adoption':{'reason':'test','attempt_id':'a','decision':{}}})
