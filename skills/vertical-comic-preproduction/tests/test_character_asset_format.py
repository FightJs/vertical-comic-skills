"""Synthetic format observations are never production visual approval."""
import copy,json,sys,unittest,tempfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import asset_format as fmt
import asset_runtime,asset_tasks
from codex_reference_contract import read_json,digest
from test_asset_runtime import AssetTests

from asset_format_fixture import reviewed

class FormatTests(unittest.TestCase):
    def test_temporary_costume_needs_same_four_full_body_views(self):
        task={'character_id':'C','costume_id':'S','publication_required':False}
        contract=fmt.contract(task)
        self.assertEqual(set(contract['required_views']),{'main_full_body','front','side','back'})
        self.assertTrue(contract['full_body_required'])
        self.assertIn('纯白空白',fmt.prompt_block(task))
        bad=reviewed('hash');bad['checks'].pop('blank_background');self.assertTrue(fmt.review_errors(bad,'hash'))
        self.assertEqual(fmt.review_errors(fmt.review_template('hash'),'hash')==[],False)
    def test_wrong_angle_crop_or_missing_view_cannot_pass(self):
        good=reviewed('hash');self.assertEqual(fmt.review_errors(good,'hash'),[])
        for change in ('angle','crop','missing','image'):
            bad=copy.deepcopy(good)
            if change=='angle':bad['views']['side']['angle_degrees']=45
            elif change=='crop':bad['views']['back']['full_body']=False
            elif change=='missing':del bad['views']['main_full_body']
            else:bad['image_sha256']='other'
            self.assertTrue(fmt.review_errors(bad,'hash'),change)
    def test_compile_actual_prompt_and_save_use_exact_same_format(self):
        fixture=AssetTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        basis=read_json(fixture.root/'basis.json');basis['asset_tasks'][0].update(character_id='C',costume_id='S')
        fixture.spec['visual_basis']=fixture.put('basis.json',basis)
        definition=fixture.put('asset-definition.json',fixture.spec)
        job=asset_runtime.compile_job(fixture.root,definition)[0]
        self.assertIn(fmt.PROMPT_MARKER,job['arguments']['prompt'])
        self.assertIn('90',job['arguments']['prompt']);self.assertIn('鞋',job['arguments']['prompt'])
        ack=asset_runtime.submit(fixture.root,job)
        returned=fixture.result();req=read_json(fixture.root/'request.json');req['arguments']=job['arguments'];returned['request_evidence']=fixture.put('request.json',req)
        self.assertEqual(asset_runtime.save(fixture.root,ack['registration_id'],returned)['status'],'ASSET_RESULT_SAVED')
    def test_return_saving_does_not_claim_format_pass(self):
        self.assertTrue(fmt.review_errors(None,'hash'))
    def test_existing_two_view_reference_is_not_ready_for_new_use(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'image.png';p.write_bytes(b'fixture image')
            task={'asset_id':'A','character_id':'C','costume_id':'S','episode_id':'E001','panel_ids':['P001'],'visible_occurrences':1,'source_basis':'test','reference':{'path':'image.png','sha256':digest(p)}}
            result=asset_tasks.audit(root,[task])['asset_tasks'][0]
            self.assertFalse(result['ready_for_use']);self.assertEqual(result['resolution'],'review_reference_format')
            task['format_review']=reviewed(digest(p))
            self.assertTrue(asset_tasks.audit(root,[task])['asset_tasks'][0]['ready_for_use'])
    def test_basis_blocks_only_affected_panels_and_legacy_contract_survives(self):
        basis={'asset_tasks':[{'asset_id':'A','character_id':'C','costume_id':'S','panel_ids':['P001'],'reference':{'path':'a.png','sha256':'hash'}}]}
        state={'asset_format_policy':fmt.POLICY}
        self.assertEqual(set(fmt.panel_errors(state,basis)),{'P001'})
        self.assertEqual(fmt.panel_errors({},basis),{})

class AdoptionGates(unittest.TestCase):
    def test_new_publication_requires_format_review_bound_to_output(self):
        from test_costume_stability import DurableAssetTests
        import asset_catalog
        fixture=DurableAssetTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        record=fixture.record();record.pop('format_review',None);assets=fixture.root/'assets';assets.mkdir()
        with self.assertRaisesRegex(ValueError,'ASSET_FORMAT'):asset_catalog.publish(assets,record,fixture.image,reuse_plan=fixture.reuse)
        record['format_review']=reviewed(record['sha256'])
        self.assertEqual(asset_catalog.publish(assets,record,fixture.image,reuse_plan=fixture.reuse)['status'],'PUBLISHED')
    def test_new_boundary_rejects_partial_reference_legacy_unchanged(self):
        import handoff_continuity as hc
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'image.png').write_bytes(b'fixture')
            record={'policy':hc.POLICY,'asset_format_policy':fmt.POLICY,'book_id':'B','source_package_id':'K','next_episode_id':'E002','characters':[{'character_id':'C','costume_id':'S','appearance_state_id':'AS','verification_status':'CONFIRMED','identity_basis':'synthetic','last_confirmed_source_panel':'E001-P001','applicability':'E002-P001','reference':{'path':'image.png','sha256':digest(root/'image.png')}}]}
            with self.assertRaisesRegex(ValueError,'ASSET_FORMAT'):hc.validate(record,root)
            old=copy.deepcopy(record);old.pop('asset_format_policy');self.assertEqual(hc.validate(old,root)['status'],'BOUNDARY_EVIDENCE_VALID')
            record['characters'][0]['format_review']=reviewed(digest(root/'image.png'))
            self.assertEqual(hc.validate(record,root)['status'],'BOUNDARY_EVIDENCE_VALID')

class RuntimeGates(unittest.TestCase):
    def fixture(self):
        from test_exception_preparation import Flow
        f=Flow();f.setUp();self.addCleanup(f.doCleanups);return f
    def install_basis(self,f):
        from test_panel_readiness import fixtures
        state=read_json(f.path);basis=read_json(f.f.template/state['visual_basis']['path'])
        bad=reviewed('hash');bad['views']['side']=None
        basis['asset_tasks']=[{'asset_id':'A','character_id':'C','costume_id':'S','panel_ids':['P001'],'reference':{'path':'a.png','sha256':'hash'},'format_review':bad}]
        state['visual_basis']=fixtures.write(f.f.template,'format-basis.json',basis)
        audit=read_json(f.f.template/state['semantic_audit']['path']);audit['visual_basis']=state['visual_basis']
        state['semantic_audit']=fixtures.write(f.f.template,'format-audit.json',audit)
        f.path.write_text(json.dumps(state));return state
    def test_malformed_view_is_hold_not_exception(self):
        r=reviewed('hash');r['views']['side']=None
        self.assertTrue(fmt.review_errors(r,'hash'))
    def test_runtime_rechecks_format_even_after_prior_ordinary_finalize(self):
        import preparation_review as entry,input_semantics as sem
        f=self.fixture();self.install_basis(f);entry.finalize(f.path)
        state=read_json(f.path);state['asset_format_policy']=fmt.POLICY
        result=sem.coverage(state,f.f.template)
        self.assertNotEqual(result['status'],'PREPRODUCTION_INPUTS_READY')
        self.assertIn('ASSET_FORMAT',str(result))
    def test_unrelated_scoped_prepare_survives_bad_review(self):
        import preparation_review as entry
        f=self.fixture();state=self.install_basis(f);state['asset_format_policy']=fmt.POLICY;f.path.write_text(json.dumps(state))
        self.assertEqual([r['panel_id'] for r in entry.prepare(f.path,['P002'])['panels']],['P002'])
    def test_boundary_policy_must_match_containing_new_episode(self):
        import handoff_continuity as hc
        with self.assertRaisesRegex(ValueError,'ASSET_FORMAT'):
            hc.require_format_policy({'episodes':[{'asset_format_policy':fmt.POLICY}]},{})
        hc.require_format_policy({'episodes':[{}]},{})
