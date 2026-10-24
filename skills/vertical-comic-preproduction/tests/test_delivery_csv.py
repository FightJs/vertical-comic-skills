import copy,csv,io,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from delivery_csv import render,OVERVIEW,DETAILS

class CsvTests(unittest.TestCase):
    def index(self):
        issue={'id':'I-1','category':2,'certainty':'confirmed','location':'左手，指尖',
               'problem':'手指"重叠"\n连接错误','target':'自然连接','handling':'人工修正'}
        return {'episode_id':'E001','panels':[
            {'panel_id':'P001','attempt_id':'old-adopted','outcome':'MANUAL_RETOUCH',
             'delivered_image':{'path':'图片/P001_old.png'},'issues':[issue]},
            {'panel_id':'P002','attempt_id':'r1','outcome':'DELIVERABLE',
             'delivered_image':{'path':'图片/P002.png'},'issues':[]}]}
    def rows(self,data):return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    def test_exact_adopted_rows_and_special_characters(self):
        index=self.index();before=copy.deepcopy(index);result=render([index],episode_prefix=True)
        self.assertEqual(index,before)
        self.assertTrue(result[OVERVIEW].startswith(b'\xef\xbb\xbf'))
        rows=self.rows(result[OVERVIEW]);details=self.rows(result[DETAILS])
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['采用版本'],'old-adopted')
        self.assertEqual(rows[0]['图片路径'],'E001/图片/P001_old.png')
        self.assertEqual(rows[1]['遗留问题数量'],'0')
        self.assertEqual(details[0]['当前问题'],index['panels'][0]['issues'][0]['problem'])
        self.assertEqual(details[0]['具体位置'],'左手，指尖')
    def test_multiple_issues_and_priority_preserve_source_rows(self):
        index=self.index();i=copy.deepcopy(index['panels'][0]['issues'][0]);i.update(id='I-2',category=1)
        index['panels'][1].update(issues=[i],outcome='MANUAL_PRIORITY')
        result=render([index]);self.assertEqual(self.rows(result[DETAILS])[0]['格号'],'P002')
        self.assertEqual([r['格号'] for r in self.rows(result[OVERVIEW])],['P001','P002'])
    def test_incomplete_unknown_and_no_issues_not_declared_clean(self):
        index=self.index();row=index['panels'][1];row.update(outcome='INCOMPLETE',incomplete_reasons=['UNKNOWN'])
        row.pop('delivered_image');result=render([index]);summary=self.rows(result[OVERVIEW])[1]
        self.assertEqual(summary['图片路径'],'');self.assertIn('UNKNOWN',summary['问题摘要'])
        index['panels'][0]['issues'][0]['certainty']='unverified'
        self.assertIn('未核实',self.rows(render([index])[DETAILS])[0]['确认情况'])
    def test_duplicate_rows_rejected(self):
        index=self.index()
        with self.assertRaises(ValueError):render([index,index])
    def test_formula_shaped_problem_is_text(self):
        index=self.index();index['panels'][0]['issues'][0]['problem']='=1+1'
        self.assertEqual(self.rows(render([index])[DETAILS])[0]['当前问题'],"'=1+1")
