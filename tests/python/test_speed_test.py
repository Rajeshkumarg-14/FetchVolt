import io
import threading
import unittest
from unittest.mock import Mock, patch
import speed_test as speed
from desktop import Desktop


class Response(io.BytesIO):
    status = 200
    def getheader(self, name, default=None):
        return self.headers.get(name, default)
    def __init__(self, body, **headers):
        super().__init__(body)
        self.headers = headers
        self.reads = []
    def read(self, amount=-1):
        self.reads.append(amount)
        return super().read(amount)


class SpeedTests(unittest.TestCase):
    def setUp(self):
        self.service = speed.SpeedTest()
        self.leases = []
        self.responses = []
    def serve(self, url, adapter, headers, **options):
        self.assertEqual(adapter, 13)
        self.assertTrue(options['public_only'])
        self.assertEqual(options['redirect_limit'], 1)
        self.assertEqual(options['response_timeout'], 12)
        count = int(url.rsplit('=', 1)[1])
        response = Response(b'x' * count, **{'Content-Length': str(count)})
        lease = Mock()
        self.leases.append(lease); self.responses.append(response)
        return lease, response
    def run_sample(self):
        with patch.object(speed, 'request', side_effect=self.serve), patch.object(speed, 'SAMPLE_BYTES', 200000):
            self.assertIsNone(self.service.start(13, 'Wi-Fi'))
            self.service._thread.join(3)
        self.assertFalse(self.service._thread.is_alive())
        return self.service.snapshot()
    def test_actual_received_bytes_and_timing_use_bounded_reads(self):
        result = self.run_sample()
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(result['bytes'], 200000)
        self.assertGreater(result['rate'], 0)
        self.assertGreaterEqual(result['latency'], 0)
        self.assertTrue(all(response.closed for response in self.responses))
        self.assertTrue(all(lease.close.call_count == 1 for lease in self.leases))
        self.assertLessEqual(max(self.responses[-1].reads), 65536)
    def test_history_is_bounded_and_snapshot_does_not_expose_mutable_history(self):
        for _ in range(7): self.run_sample()
        data = self.service.snapshot()
        self.assertEqual(len(data['history']), 5)
        data['history'][0]['rate'] = -1
        self.assertGreater(self.service.snapshot()['history'][0]['rate'], 0)
    def test_request_error_is_private_and_does_not_create_success(self):
        with patch.object(speed, 'request', side_effect=OSError('sensitive url and ip')), patch.object(speed, 'failure') as log:
            self.service.start(13, 'Wi-Fi'); self.service._thread.join(2)
        result = self.service.snapshot()
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('sensitive', str(result))
        self.assertEqual(result['history'], [])
        log.assert_called_once()
    def test_incorrect_size_encoding_status_or_header_closes_resources(self):
        for status, headers in [(403, {}), (200, {'Content-Length': 'bad'}), (200, {'Content-Length': '4'}), (200, {'Content-Encoding': 'gzip'})]:
            with self.subTest(status=status, headers=headers):
                lease=Mock(); response=Response(b'', **headers); response.status=status
                with patch.object(speed, 'request', return_value=(lease,response)):
                    with self.assertRaises((ValueError, OSError)): self.service._open(13,0)
                lease.close.assert_called_once(); self.assertTrue(response.closed)
    def test_incomplete_body_fails_without_success_history(self):
        def truncated(url, adapter, headers, **options):
            lease, response = self.serve(url,adapter,headers,**options)
            if 'bytes=0' not in url: response.seek(0,2)
            return lease,response
        with patch.object(speed,'request',side_effect=truncated), patch.object(speed,'failure'):
            self.service.start(13,'Wi-Fi'); self.service._thread.join(2)
        self.assertEqual(self.service.snapshot()['state'],'failed')
        self.assertEqual(self.service.snapshot()['history'],[])
    def test_concurrent_start_rejected_and_cancel_interrupts_socket(self):
        reached=threading.Event(); finish=threading.Event()
        response=Response(b''); lease=Mock()
        def blocked(*args, **kwargs):
            reached.set(); finish.wait(2); return lease,response
        with patch.object(speed,'request',side_effect=blocked):
            self.service.start(13,'Wi-Fi'); self.assertTrue(reached.wait(1))
            self.assertIn('already running',self.service.start(13,'USB'))
            self.service.cancel(); finish.set(); self.service._thread.join(2)
        self.assertEqual(self.service.snapshot()['state'],'cancelled')
        self.assertTrue(response.closed); lease.close.assert_called_once()
        with self.service._lock: self.service._lease=lease
        self.service.cancel(); lease.socket.shutdown.assert_called_once()
    def test_cancel_before_open_never_issues_network_request(self):
        self.service.cancel()
        with patch.object(speed,'request') as request:
            with self.assertRaises(InterruptedError): self.service._open(13,0)
            request.assert_not_called()
    def test_service_is_idle_and_does_not_start_on_construction(self):
        self.assertEqual(self.service.snapshot()['state'],'idle')
        self.assertIsNone(self.service._thread)


class SpeedApiTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('desktop.History'))
        self.api=Desktop(restore=False)
        self.api._rows=[{'index':13,'name':'Wi-Fi','gateway':True,'status':'Up'}]
    def test_arbitrary_and_boolean_adapter_ids_never_start(self):
        for value in [True,False,{},'13',99,None]:
            self.assertIsInstance(self.api.start_speed_test(value),str)
        self.assertIsNone(self.api._speed_test._thread)
    def test_connected_adapter_only_and_active_download_exclusion(self):
        with patch.object(self.api._speed_test,'start') as start:
            self.api._jobs={1:{'view':{'state':'running'}}}
            self.assertIn('Pause',self.api.start_speed_test(13)); start.assert_not_called()
            self.api._jobs={}; self.api._rows[0]['gateway']=False
            self.assertIsInstance(self.api.start_speed_test(13),str); start.assert_not_called()
            self.api._rows[0]['gateway']=True
            self.api.start_speed_test(13); start.assert_called_once_with(13,'Wi-Fi')
    def test_closing_cancels_speed_test_and_rejects_new_test(self):
        self.api._shutdown_requested=True
        self.assertIn('closing',self.api.start_speed_test(13))
        with patch.object(self.api._speed_test,'cancel') as cancel:
            self.assertTrue(self.api._on_closing()); cancel.assert_called_once()
