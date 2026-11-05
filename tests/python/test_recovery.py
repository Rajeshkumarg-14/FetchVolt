import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import net_booster as engine
import recovery
from tests.python.test_net_booster import Response


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        folder=self.root/'records'
        folder.mkdir()
        self.enterContext(patch.object(recovery,'directory',return_value=folder))
        self.body=bytes(range(128))
        self.identifier=uuid4().hex
        self.target=self.root/'file.bin'
        self.partial=self.root/'.net-booster-recovery.part'
        self.partial.write_bytes(self.body[:32]+bytes(96))
        self.record=recovery.create(self.identifier,'https://example.test/file',self.target,self.partial,
                                    128,'"stable"',32)
        self.record.completed(0,hashlib.sha256(self.body[:32]).hexdigest())

    def test_resume_reads_only_missing_ranges_then_removes_checkpoint(self):
        ranges=[]
        def request(url,adapter,headers):
            low,high=map(int,headers['Range'][6:].split('-'))
            ranges.append((low,high))
            return io.BytesIO(),Response(206,self.body[low:high+1],**{
                'Content-Range':f'bytes {low}-{high}/128','ETag':'"stable"'})
        with patch.object(engine,'request',side_effect=request),patch.object(engine,'scan_file'):
            _,totals=engine.download('https://example.test/file',self.target,{'Wi-Fi':1},lambda *_:None,
                live_links=engine.LiveLinks({'Wi-Fi':1}),recovery_id=self.identifier)
        self.assertEqual(self.target.read_bytes(),self.body)
        self.assertEqual(totals['Recovered'],32)
        self.assertNotIn((0,31),ranges)
        self.assertEqual(sum(totals.values()),128)
        self.assertFalse(self.record.path.exists())

    def test_modified_saved_chunk_is_rejected_from_recovery_set(self):
        with self.partial.open('r+b') as file:
            file.write(b'x')
        self.assertEqual(self.record.verified(),set())

    def test_changed_server_etag_preserves_saved_progress_for_review(self):
        reply=Response(206,b'\0',**{'Content-Range':'bytes 0-0/128','ETag':'"changed"'})
        with patch.object(engine,'request',return_value=(io.BytesIO(),reply)),self.assertRaisesRegex(ValueError,'changed'):
            engine.download('https://example.test/file',self.target,{'Wi-Fi':1},lambda *_:None,
                live_links=engine.LiveLinks({'Wi-Fi':1}),recovery_id=self.identifier)
        self.assertTrue(self.partial.exists())
        self.assertTrue(self.record.path.exists())
        self.assertFalse(self.target.exists())

    def test_cancel_discards_staging_and_checkpoint(self):
        control=engine.LiveLinks({'Wi-Fi':1})
        control.cancel()
        reply=Response(206,b'\0',**{'Content-Range':'bytes 0-0/128','ETag':'"stable"'})
        with patch.object(engine,'request',return_value=(io.BytesIO(),reply)),self.assertRaises(engine.DownloadCancelled):
            engine.download('https://example.test/file',self.target,{'Wi-Fi':1},lambda *_:None,
                live_links=control,recovery_id=self.identifier)
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.record.path.exists())

    def test_pending_records_validate_paths_before_use(self):
        self.record.data['partial']=str(self.root/'unrelated.txt')
        self.record.save()
        self.assertEqual(recovery.pending(),[])
