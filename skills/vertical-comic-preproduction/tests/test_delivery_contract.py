"""Capacity and completion constraints; temporary files only, no image service."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import delivery_contract as d
import production_progress as progress


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.sp=self.root/'E001/00_输入审计/state.json'
        self.sp.parent.mkdir(parents=True);self.sp.write_text(json.dumps({'book_id':'UNIT','episode_id':'E001','panels':[]}))
        self.ref=d.initialize(self.root,'preparation',[self.sp],package_mode='single_zip',max_file_bytes=65536)
        self.identity=Path(self.ref['path']);self.value=d.load_identity(self.identity)

    def test_role_defaults_and_startup_match(self):
        import inspect,comic_start
        ref=d.initialize(self.root/'default','preparation',[self.sp])
        self.assertEqual(d.load_identity(ref['path'])['package_mode'],'allow_parts')
        self.assertEqual(inspect.signature(comic_start.prepare).parameters['delivery_mode'].default,'allow_parts')
        self.assertNotIn('max_file_bytes',inspect.signature(comic_start.receive).parameters)
        prod=d.load_identity(d.initialize(self.root/'prod','production',[self.sp])['path'])
        self.assertIsNone(prod['max_file_bytes']);self.assertEqual(prod['package_mode'],'single_zip')
        self.assertEqual(prod['csv_policy'],d.CSV_POLICY)
        with self.assertRaises(ValueError):d.initialize(self.root/'bad','production',[self.sp],max_file_bytes=900000000)
        with self.assertRaises(ValueError):d.validate_requirements({**prod,'csv_policy':None})

    def test_production_artifact_over_one_gigabyte_has_no_size_gate(self):
        prod=d.load_identity(d.initialize(self.root/'prod','production',[self.sp])['path'])
        # Actual sparse file tests byte-size gate, not ZIP structural validity.
        file=self.root/'large.zip'
        with file.open('wb') as stream:stream.truncate(1000000001)
        row={**d.reference(file),'bytes':file.stat().st_size}
        self.assertEqual(d.validate_artifact_set(prod,[row]),[row])
        with self.assertRaisesRegex(ValueError,'交付记录'):d.validate_artifact_set(prod,[{**row,'sha256':'wrong'}])

    def test_contract_reuse_without_rewriting_or_relaxation(self):
        before=self.identity.read_bytes()
        self.assertEqual(d.initialize(self.root,'preparation',[self.sp],package_mode='single_zip',max_file_bytes=65536),self.ref)
        self.assertEqual(self.identity.read_bytes(),before)
        with self.assertRaises(ValueError):d.initialize(self.root,'preparation',[self.sp],package_mode='allow_parts')

    def test_exact_limit_and_one_byte_over(self):
        file=self.root/'valid.zip';file.write_bytes(b'x'*65536)
        row={**d.reference(file),'bytes':65536}
        self.assertEqual(d.validate_artifact_set(self.value,[row]),[row])
        file.write_bytes(b'x'*65537)
        with self.assertRaisesRegex(ValueError,'超出1'):
            d.validate_artifact_set(self.value,[{**d.reference(file),'bytes':65537}])

    def test_strict_single_never_implicitly_splits(self):
        rows=[]
        for name in ('a.zip','b.zip'):
            file=self.root/name;file.write_bytes(b'a');rows.append({**d.reference(file),'bytes':1})
        with self.assertRaisesRegex(ValueError,'单ZIP'):d.validate_artifact_set(self.value,rows)
        value={**self.value,'package_mode':'allow_parts'}
        self.assertEqual(d.validate_artifact_set(value,rows),rows)
        with self.assertRaises(ValueError):d.validate_artifact_set(value,[rows[0],rows[0]])

    def test_wrong_hash_size_empty_or_missing_file(self):
        p=self.root/'a.zip';p.write_bytes(b'abc');row={**d.reference(p),'bytes':3}
        for rows in ([],[{**row,'bytes':2}],[{**row,'sha256':'false'}],[{**row,'path':str(self.root/'missing.zip')}]):
            with self.assertRaises(ValueError):d.validate_artifact_set(self.value,rows)

    def test_invalid_cap_and_scope_are_not_accepted(self):
        for limit in (True,0,900000001):
            with self.assertRaises(ValueError):d.validate_requirements({**self.value,'max_file_bytes':limit})
        with self.assertRaises(ValueError):d.validate_requirements({**self.value,'states':[]})

    def test_missing_contract_cannot_be_display_warning_fallback(self):
        task={'role':'preparation','scope':self.value['scope'],'states':self.value['states'],
              'completion_policy':d.POLICY,'delivery_identity':self.ref}
        (self.identity.parent/d.CONTRACT).unlink()
        with self.assertRaisesRegex(ValueError,'交付记录'):d.for_display(self.root/'display',task)

    def test_missing_identity_and_partial_initialization_hold(self):
        self.identity.unlink()
        with self.assertRaisesRegex(ValueError,'身份缺失'):d.for_display(self.root/'display')
        with self.assertRaisesRegex(ValueError,'未闭合'):d.initialize(self.root,'preparation',[self.sp])

    def test_state_scope_change_invalidates_identity(self):
        self.sp.write_text(json.dumps({'book_id':'OTHER','episode_id':'E001'}))
        with self.assertRaisesRegex(ValueError,'书话'):d.load_identity(self.identity)

    def test_missing_receipt_stops_new_complete_before_content_gate(self):
        display=self.root/'display';display.mkdir()
        (display/'task.json').write_text(json.dumps({'policy':'task_progress_v1','role':'preparation',
            'scope':self.value['scope'],'states':self.value['states'],'completion_policy':d.POLICY,'delivery_identity':self.ref}))
        with self.assertRaisesRegex(ValueError,'必须提供'):progress.complete(display,self.root/'not-generated.zip')
        self.assertFalse((display/'delivered.json').exists())

    def test_legacy_display_without_contract_is_unchanged(self):
        other=self.root/'legacy/display'
        self.assertEqual(d.for_display(other), (None,None))

    def test_capacity_reads_only_adopted_metadata(self):
        image=self.root/'E001/image.png';image.write_bytes(b'12345')
        value=json.loads(self.sp.read_text());value['panels']=[{
            'attempt_id':'new-failed','output':{'path':'wrong-failed.png'},
            'adoption':{'attempt_id':'old-good'},'attempt_history':[
                {'attempt_id':'old-good','output':{'path':'image.png'}}]}]
        self.sp.write_text(json.dumps(value))
        with patch.object(Path,'read_bytes',side_effect=AssertionError('no image read')):
            report=d.capacity_summary([self.sp],4)
        self.assertEqual(report['adopted_bytes'],5);self.assertEqual(report['estimated_image_bytes'],20)
        self.assertIsNone(report['actual_zip_bytes'])


if __name__=='__main__':unittest.main()
