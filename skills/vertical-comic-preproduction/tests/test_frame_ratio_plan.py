"""Frame-ratio coverage and real shared gate regressions; no production calls."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
from codex_reference_contract import digest
from frame_ratio_plan import POLICY,ALLOWED,PORTRAIT,statistics,distribution_errors,plan_errors,panel_errors,execution_block,actual_review,image_errors,template

RATIOS30=['4:5','9:16','1:1','4:5','3:4','9:16','3:4','1:1','4:5','3:4','9:16','5:4','3:4','9:16','4:5','9:16','5:4','3:4','9:16','4:5','1:1','3:4','9:16','4:5','3:4','16:9','9:16','3:4','4:5','16:9']

def rows(ratios):return [{'panel_id':f'P{i+1:03d}','frame_ratio':r,'frame_ratio_reason':f'SYNTHETIC focal subject and crop {i+1}'} for i,r in enumerate(ratios)]

class FrameRatios(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.rows=rows(RATIOS30);ids=[p['panel_id'] for p in self.rows]
        self.source={'panel_ids':ids,'locked_scripts':{p:{} for p in ids}}
        self.state={'book_id':'UNIT','episode_id':'E000','source_snapshot':self.write('snapshot.json',self.source),'frame_ratio_policy':POLICY}
        self.plan={**template(self.state,self.source),'panels':self.rows};self.state['frame_ratio_plan']=self.write('ratio-plan.json',self.plan)
    def write(self,name,data):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False), encoding='utf-8', newline='\n');return {'path':name,'sha256':digest(path)}
    def test_previous_30_panel_distribution_remains_valid(self):
        self.assertEqual(plan_errors(self.state,self.root),[])
        stats=statistics(self.rows);self.assertEqual(stats['portrait_count'],23);self.assertEqual(stats['minimum_portrait_count'],23);self.assertEqual(stats['counts'],{'9:16':8,'3:4':8,'4:5':7,'1:1':3,'5:4':2,'16:9':2})
    def test_35_panel_minimum_is_27_portraits(self):
        non={3,8,12,16,21,25,29,34};ratios=[];v=0;other=0
        for i in range(1,36):
            if i in non:ratios.append(ALLOWED[3+other%3]);other+=1
            else:ratios.append(PORTRAIT[v%3]);v+=1
        self.assertEqual(distribution_errors(rows(ratios)),[]);self.assertEqual(statistics(rows(ratios))['minimum_portrait_count'],27)
    def test_exactly_75_percent_is_not_enough(self):
        self.assertTrue(any('严格大于' in e for e in distribution_errors(rows(['9:16','3:4','1:1','4:5']))))
    def test_all_one_ratio_is_rejected(self):
        self.assertTrue(any('通体同一' in e for e in distribution_errors(rows(['9:16']*30))))
    def test_unsupported_ratio_and_adjacent_repetition_rejected(self):
        self.assertTrue(distribution_errors(rows(['3:2'])))
        changed=copy.deepcopy(self.rows);changed[0]['frame_ratio']=changed[1]['frame_ratio'];self.assertTrue(any('相邻' in e for e in distribution_errors(changed)))
    def test_square_wide_cluster_at_end_is_rejected(self):
        cluster=[p for p in self.rows if p['frame_ratio'] in PORTRAIT]+[p for p in self.rows if p['frame_ratio'] not in PORTRAIT]
        self.assertTrue(any('方形/横版集中' in e for e in distribution_errors(cluster)))
    def test_source_order_scope_and_hash_are_bound(self):
        self.plan['panels'][0],self.plan['panels'][1]=self.plan['panels'][1],self.plan['panels'][0];self.state['frame_ratio_plan']=self.write('ratio-plan.json',self.plan);self.assertTrue(plan_errors(self.state,self.root))
        self.plan['panels']=self.rows;self.plan['episode_id']='OTHER';self.state['frame_ratio_plan']=self.write('ratio-plan.json',self.plan);self.assertTrue(plan_errors(self.state,self.root))
        (self.root/'ratio-plan.json').write_text('{}', encoding='utf-8', newline='\n');self.assertTrue(plan_errors(self.state,self.root))
    def test_half_two_does_not_reset_episode_portrait_fraction(self):
        half=self.rows[15:];self.assertEqual(statistics(half)['portrait_count'],11)
        self.assertEqual(plan_errors(self.state,self.root),[]);self.assertEqual(panel_errors(self.state,self.root,half),[])
    def test_prompt_must_carry_approved_ratio_block(self):
        panel=copy.deepcopy(self.rows[0]);panel.update(prompt='SYNTHETIC wrong missing execution block')
        self.assertTrue(panel_errors(self.state,self.root,[panel],prompt=True))
        panel['frame_ratio_execution_block']=execution_block(panel);panel['prompt']=execution_block(panel);self.assertEqual(panel_errors(self.state,self.root,[panel],prompt=True),[])
        panel['prompt']='画幅比例：9:16\n'+execution_block(panel);self.assertTrue(panel_errors(self.state,self.root,[panel],prompt=True))
        panel['frame_ratio']='9:16';self.assertTrue(panel_errors(self.state,self.root,[panel],prompt=True))
    def outputs(self,uniform=False):
        refs={}
        for r in ALLOWED:
            w,h=map(int,r.split(':'));file=self.root/(r.replace(':','_')+'.png');Image.new('RGB',(w*16,h*16),'white').save(file);refs[r]={'path':file.name,'sha256':digest(file)}
        return [{'panel_id':p['panel_id'],'output':refs['9:16' if uniform else p['frame_ratio']]} for p in self.rows]
    def test_final_images_checked_by_real_pixel_dimensions(self):
        review=actual_review(self.state,self.root,self.outputs());self.assertEqual(review['errors'],[]);self.assertEqual(review['statistics']['portrait_count'],23)
    def test_uniform_real_outputs_fail_even_when_plan_is_diverse(self):
        review=actual_review(self.state,self.root,self.outputs(True));self.assertTrue(review['errors']);self.assertEqual(review['statistics']['counts']['9:16'],30);self.assertTrue(any('通体同一' in e for e in review['errors']))
    def test_large_tolerance_cannot_hide_wrong_frame_variant(self):
        self.assertTrue(image_errors({'frame_ratio':'9:16','ratio_tolerance':0.9},[100,100]))
    def test_template_never_defaults_to_9_16(self):
        candidate=template(self.state,self.source);self.assertTrue(all(p['frame_ratio'] is None for p in candidate['panels']))
    def test_old_unmarked_records_remain_historical(self):
        self.assertEqual(plan_errors({},self.root),[]);self.assertEqual(panel_errors({},self.root,rows(['3:2'])),[])
        missing=copy.deepcopy(self.state);missing.pop('frame_ratio_policy');self.assertTrue(plan_errors(missing,self.root))
        self.assertTrue(plan_errors({'requested_framing':{'policy':POLICY}},self.root))
    def test_full_half_generate_binds_ratio_plan_and_blocks_deleted_policy(self):
        import test_execution_lifecycle as lifecycle
        from execution_contract import toolchain
        from _historical_fixture import evaluate
        root=self.root/'episode';s,m,p,shots=lifecycle.build_calibration(root);src=lifecycle.read(root,s['source_snapshot'])
        plan={**template(s,src),'panels':rows(['9:16','3:4','4:5','9:16'])};ref=lifecycle.write(root,'ratio-plan.json',plan)
        headers={'frame_ratio_policy':POLICY,'frame_ratio_plan':ref,'source_snapshot':s['source_snapshot']};s.update(headers);m.update(headers);shots.update(headers)
        by_id={x['panel_id']:x for x in plan['panels']}
        from repair_prompt_package import camera_block
        for panel in [p,*shots['panels']]:
            panel.update(by_id[panel['panel_id']]);panel['frame_ratio_execution_block']=execution_block(panel);panel['camera_execution_block']=camera_block(panel,panel,None,None)
            panel['prompt']='\n\n'.join(panel[k] for k in ('camera_execution_block','content_execution_block','identity_execution_block','reference_usage_block','style_execution_block','negative_prompt','frame_ratio_execution_block'))
        shot_ref=lifecycle.write(root,'H001-shots.json',shots);s['half_inputs']['H001']['shot_manifest']=shot_ref
        audit=lifecycle.read(root,s['half_inputs']['H001']['semantic_audit']);audit['shot_manifest']=shot_ref;audit_ref=lifecycle.write(root,'semantic.json',audit);s['half_inputs']['H001']['semantic_audit']=audit_ref
        s['half_gates']['H001']['shot_design']=lifecycle.approve([s['half_inputs']['H001']['visual_basis'],shot_ref,audit_ref,ref]);s['toolchain']=toolchain()
        (root/'P001/prompt.txt').write_text(p['prompt'], encoding='utf-8', newline='\n');lifecycle.write(root,'P001/提示词.json',p)
        s['panels'][0]['package_manifest']=lifecycle.write(root,'全话提示词索引.json',m);s['panels'][0]['shot_subset']=lifecycle.write(root,'shot-subset.json',{**shots,'panels':[shots['panels'][0]]})
        result=evaluate(s,root,'generate','P001');self.assertEqual(result['next_action'],'READY_FOR_HALF_PANEL',result)
        m.pop('frame_ratio_policy');s['panels'][0]['package_manifest']=lifecycle.write(root,'missing-ratio-manifest.json',m)
        result=evaluate(s,root,'generate','P001');self.assertEqual(result['status'],'HOLD');self.assertTrue(any('同一全话画幅计划' in e for e in result['errors']),result)
        m.update(headers);lifecycle.create_return(root,s,m,p,'VISUAL_PASS',1)
        result=evaluate(s,root);self.assertEqual(result['eligible_panel_ids'],['P002'],result)

if __name__=='__main__':unittest.main()
