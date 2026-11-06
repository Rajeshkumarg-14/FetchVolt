import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import net_booster as engine
from tests.python.test_net_booster import Response


class LiveLinkTests(unittest.TestCase):
    @patch.object(engine, 'STREAMS_PER_LINK', 1)
    def test_adapter_can_join_without_redownloading_completed_ranges(self):
        body = bytes(range(128))
        started = threading.Event()
        usb = threading.Event()
        released = threading.Event()
        links = engine.LiveLinks({'Wi-Fi': 1})
        seen = set()
        seen_lock = threading.Lock()

        def request(url, adapter, headers):
            start, end = map(int, headers['Range'][6:].split('-'))
            if 'If-Range' in headers:
                with seen_lock:
                    self.assertNotIn(start, seen)
                    seen.add(start)
                if adapter == 1 and start == 0:
                    started.set()
                    self.assertTrue(released.wait(5))
                if adapter == 2:
                    usb.set()
            return io.BytesIO(), Response(206, body[start:end + 1], **{
                'Content-Range': f'bytes {start}-{end}/{len(body)}', 'ETag': '"same"',
            })

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(engine, 'request', side_effect=request),
            patch.object(engine, 'scan_file'),
            patch.object(engine, 'CHUNK', 16),
        ):
            path = Path(directory) / 'file.bin'
            result = []
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                job = pool.submit(engine.download, 'https://example.test/file', path, {'Wi-Fi': 1},
                                  lambda *_: None, live_links=links)
                try:
                    self.assertTrue(started.wait(3))
                    self.assertTrue(links.update({'Wi-Fi': 1, 'USB': 2}))
                    self.assertTrue(usb.wait(3))
                finally:
                    released.set()
                result = job.result(timeout=5)
            self.assertEqual(path.read_bytes(), body)
            self.assertTrue(all(result[1].values()))
            self.assertEqual(sum(result[1].values()), len(body))

    def test_single_stream_refuses_mid_transfer_changes(self):
        links = engine.LiveLinks({'Wi-Fi': 1})
        self.assertFalse(links.update({'USB': 2}))
        links.set_mode('single', {'Wi-Fi': 1})
        self.assertFalse(links.update({'USB': 2}))
        self.assertEqual(links.snapshot()[2], {'Wi-Fi': 1})

    def test_pause_and_resume_retain_completed_ranges(self):
        selection = engine.LiveLinks({'Wi-Fi': 1})
        selection.set_mode('range')
        complete = []
        paused = threading.Event()
        release = threading.Event()

        def fetch(name, offset, adapter):
            selection.check()
            complete.append(offset)
            if offset == 0:
                self.assertTrue(selection.pause())
                paused.set()

        with __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(engine.run_live_ranges, selection, iter([0, 10, 20]), fetch)
            self.assertTrue(paused.wait(3))
            self.assertEqual(complete, [0])
            selection.resume()
            future.result(timeout=3)
        self.assertEqual(complete, [0, 10, 20])

    @patch.object(engine, 'STREAMS_PER_LINK', 1)
    def test_connection_recovers_without_repeating_completed_ranges(self):
        selection = engine.LiveLinks({'Wi-Fi': 1})
        selection.set_mode('range')
        attempts = []
        def fetch(name, offset, adapter):
            attempts.append(offset)
            if attempts == [0, 10]:
                raise ConnectionError('Connection dropped.')
        with patch.object(selection, 'wait'):
            engine.run_live_ranges(selection, iter([0, 10, 20]), fetch)
        self.assertEqual(attempts, [0, 10, 10, 20])

    def test_each_adapter_runs_several_streams_at_once(self):
        selection = engine.LiveLinks({'USB': 1})
        selection.set_mode('range')
        active = peak = 0
        lock = threading.Lock()
        def fetch(name, offset, adapter):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            threading.Event().wait(.05)
            with lock:
                active -= 1
        engine.run_live_ranges(selection, iter(range(0, 160, 10)), fetch)
        self.assertEqual(peak, engine.STREAMS_PER_LINK)

    def test_streams_are_capped_per_adapter_and_cover_every_range_once(self):
        selection = engine.LiveLinks({'Wi-Fi': 1, 'USB': 2})
        selection.set_mode('range')
        active = {'Wi-Fi': 0, 'USB': 0}
        peak = dict(active)
        done = []
        lock = threading.Lock()
        def fetch(name, offset, adapter):
            with lock:
                active[name] += 1
                peak[name] = max(peak[name], active[name])
            threading.Event().wait(.03)
            with lock:
                active[name] -= 1
                done.append(offset)
        engine.run_live_ranges(selection, iter(range(0, 400, 10)), fetch)
        self.assertEqual(sorted(done), list(range(0, 400, 10)))
        self.assertEqual(peak, {'Wi-Fi': engine.STREAMS_PER_LINK, 'USB': engine.STREAMS_PER_LINK})

    def test_failed_stream_range_is_retried_not_lost(self):
        selection = engine.LiveLinks({'Wi-Fi': 1, 'USB': 2})
        selection.set_mode('range')
        done = []
        failed_once = []
        def fetch(name, offset, adapter):
            if name == 'Wi-Fi':
                failed_once.append(offset)
                raise ConnectionError('Connection dropped.')
            done.append(offset)
        with patch.object(selection, 'wait'):
            engine.run_live_ranges(selection, iter(range(0, 100, 10)), fetch)
        self.assertTrue(failed_once)
        self.assertEqual(sorted(done), list(range(0, 100, 10)))

    def test_cancel_stops_a_paused_transfer(self):
        selection = engine.LiveLinks({'Wi-Fi': 1})
        selection.set_mode('range')
        selection.pause()
        selection.cancel()
        with self.assertRaises(engine.DownloadCancelled):
            engine.run_live_ranges(selection, iter([0]), lambda *_: None)

    @patch.object(engine, 'STREAMS_PER_LINK', 1)
    def test_partial_range_is_retried_without_losing_completed_bytes(self):
        body = bytes(range(128))
        control = engine.LiveLinks({'Wi-Fi': 1})
        attempts = []
        class InterruptedResponse(Response):
            def read1(self, amount=-1):
                if self.tell():
                    raise ConnectionError('Link lost after a partial write.')
                return super().read1(min(amount, 5))
        def request(url, adapter, headers):
            first,last = map(int,headers['Range'][6:].split('-'))
            headers_out = {'Content-Range': f'bytes {first}-{last}/{len(body)}', 'ETag': '"stable"'}
            if 'If-Range' not in headers:
                return io.BytesIO(), Response(206,body[first:last+1],**headers_out)
            attempts.append(first)
            response_type = InterruptedResponse if attempts == [0,32] else Response
            return io.BytesIO(), response_type(206,body[first:last+1],**headers_out)
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(engine,'request',side_effect=request),
            patch.object(engine,'scan_file'),
            patch.object(engine,'CHUNK',16),
            patch.object(control,'wait'),
        ):
            path=Path(folder)/'file.bin'
            _,totals=engine.download('https://example.test/file',path,{'Wi-Fi':1},lambda *_:None,live_links=control)
            self.assertEqual(path.read_bytes(),body)
            self.assertEqual(sum(totals.values()),len(body))
        self.assertEqual(attempts,[0,32,32,64,96])

    def test_cancelled_transfer_removes_partial_and_preserves_destination(self):
        control=engine.LiveLinks({'Wi-Fi':1})
        body=bytes(range(64))
        def request(url,adapter,headers):
            first,last=map(int,headers['Range'][6:].split('-'))
            return io.BytesIO(),Response(206,body[first:last+1],**{
                'Content-Range':f'bytes {first}-{last}/{len(body)}','ETag':'"same"'})
        def report(*_):
            control.cancel()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(engine,'request',side_effect=request),
            patch.object(engine,'scan_file') as scan,
            patch.object(engine,'CHUNK',16),
        ):
            path=Path(folder)/'file.bin'
            path.write_bytes(b'old')
            with self.assertRaises(engine.DownloadCancelled):
                engine.download('https://example.test/file',path,{'Wi-Fi':1},report,live_links=control)
            self.assertEqual(path.read_bytes(),b'old')
            self.assertEqual(list(path.parent.iterdir()),[path])
            scan.assert_not_called()
