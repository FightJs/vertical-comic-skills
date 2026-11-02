"""Synthetic packaged boundary: real existing packaging/reception code, no calls."""
import json,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_direct_handoff import DirectHandoffTests
import handoff_zip as h, handoff_delivery as d, handoff_continuity as c

class BoundaryIntegration(DirectHandoffTests):
    def test_boundary_formal_roundtrip_and_replay(self):
        source=self.base/'source';source.mkdir();image=source/'boundary/image.png';image.parent.mkdir()
        sample=os.environ.get('COMIC_ACCEPTANCE_IMAGE');expected=Path(sample).read_bytes() if sample else b'synthetic-image';image.write_bytes(expected)
        boundary={'policy':c.POLICY,'book_id':self.index['book_id'],'next_episode_id':'E001','source_package_id':self.index['package_id'],
          'characters':[{'character_id':'C','verification_status':'CONFIRMED','costume_id':'S','appearance_state_id':'AS','identity_basis':'synthetic evidence',
          'last_confirmed_source_panel':'E000-P004','applicability':'UNKNOWN','reference':{'path':'boundary/image.png','sha256':h.sha(image)}}]}
        staged=c.stage_boundary(self.package,boundary,expected_index_sha256=h.sha(self.package/h.INDEX),source_root=source)
        self.index=json.loads((self.package/h.INDEX).read_text());self.assertEqual(staged['status'],'BOUNDARY_STAGED_NOT_APPROVED')
        z,received,bound,report=self.pipeline()
        review=d.input_review(received,self.index);self.assertIn('continuity_boundary',review)
        auth=self.base/'auth.json';auth.write_text(json.dumps({'status':'APPROVED','source_kind':'user_message','source_locator':'SYNTHETIC','quote':'SYNTHETIC',
          'authorization_mode':'approved_inputs_auto_export_v1','package_id':self.index['package_id'],'approved_input_digest':review['approved_input_digest'],'after_successful_rehearsal':True}))
        out=self.base/'formal.zip';h.release(z,self.base/'rehearsal/演练报告.json',auth,out)
        assets=self.base/'assets';assets.mkdir()
        first=c.publish_from_archive(assets,out);second=c.publish_from_archive(assets,out)
        self.assertEqual(first,second)
        resolved=c.resolve(assets,self.index['book_id'],'E001');self.assertEqual(resolved['status'],'CANDIDATE_FOR_A')
        self.assertEqual((Path(resolved['record_root'])/'boundary/image.png').read_bytes(),expected)
        (Path(resolved['record_root'])/'boundary/image.png').unlink()
        partial=c.resolve(assets,self.index['book_id'],'E001')
        self.assertEqual(partial['status'],'PARTIAL_HOLD');self.assertEqual(partial['issues'][0]['character_id'],'C')
        c.publish_from_archive(assets,out)
        repaired=c.resolve(assets,self.index['book_id'],'E001')
        self.assertEqual(repaired['status'],'CANDIDATE_FOR_A')
        self.assertEqual((Path(repaired['record_root'])/'boundary/image.png').read_bytes(),expected)
