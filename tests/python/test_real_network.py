"""Real loopback HTTPS integration tests with an ephemeral, locally trusted CA.

No physical adapter is disconnected. Logical paths share Windows adapter 0.
Only scanner failures/availability and selected disk faults use injected fixtures.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import net_booster as engine
import recovery
from windows_security import ScanError

BODY = bytes(range(256)) * 4096
DIGEST = hashlib.sha256(BODY).hexdigest()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def handle_error(self, request, client_address):
        # A deliberately closed client socket is an expected fixture outcome.
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/stall-headers':
            self.server.headers_waiting.set()
            time.sleep(.8)
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/file')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        ranged = self.headers.get('Range') and self.path != '/ignore-range'
        low, high = map(int, self.headers['Range'][6:].split('-')) if ranged else (0, len(BODY)-1)
        probe = self.headers.get('Range') == 'bytes=0-0'
        with self.server.state_lock:
            self.server.requests.append((self.path, low, high, bool(self.headers.get('If-Range'))))
            cut = self.path == '/cut-once' and not probe and not self.server.cut_done
            if cut:
                self.server.cut_done = True
        body = BODY[low:high+1]
        self.send_response(206 if ranged else 200)
        self.send_header('Content-Length', str(len(body)))
        if ranged:
            extent = f'bytes {low}-{high}/{len(BODY)}'
            if self.path == '/bad-range' and not probe:
                extent = f'bytes {low+1}-{high+1}/{len(BODY)}'
            self.send_header('Content-Range', extent)
        self.send_header('ETag', '"changed"' if self.path == '/changed-etag' and not probe else '"stable"')
        self.end_headers()
        if self.path == '/stall-body' and not probe:
            time.sleep(.8)
        if self.path == '/truncate' or cut:
            self.wfile.write(body[:max(1, len(body)//2)])
            self.wfile.flush()
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        for offset in range(0, len(body), 16384):
            self.wfile.write(body[offset:offset+16384])
            self.wfile.flush()
            if self.path == '/slow' and not probe:
                time.sleep(.015)


class RealHttpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='fetchvolt-https-')
        cls.root = Path(cls.workspace.name)
        cls.cert, cls.key = cls.root/'cert.pem', cls.root/'key.pem'
        # In-memory .NET certificate creation; does not change any trust store.
        script = r'''$ErrorActionPreference='Stop';$r=[Security.Cryptography.RSA]::Create(2048);try{
$q=[Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=localhost',$r,[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1);
$s=[Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new();$s.AddDnsName('localhost');$s.AddIpAddress([Net.IPAddress]::Loopback);$q.CertificateExtensions.Add($s.Build());
$q.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true,$false,0,$true));
$c=$q.CreateSelfSigned([DateTimeOffset]::UtcNow.AddMinutes(-5),[DateTimeOffset]::UtcNow.AddDays(1));try{
[IO.File]::WriteAllText($args[0],$c.ExportCertificatePem());[IO.File]::WriteAllText($args[1],$r.ExportPkcs8PrivateKeyPem())}finally{$c.Dispose()}}finally{$r.Dispose()}'''
        script_file=cls.root/'certificate.ps1'
        script_file.write_text(script,encoding='utf-8')
        subprocess.run([shutil.which('pwsh.exe'), '-NoProfile', '-NonInteractive', '-File', str(script_file), str(cls.cert), str(cls.key)],
                       check=True, capture_output=True, timeout=15)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.cert,cls.key)
        cls.server=Server(('127.0.0.1',0),Handler)
        cls.server.socket=context.wrap_socket(cls.server.socket,server_side=True)
        cls.server.requests=[]
        cls.server.state_lock=threading.Lock()
        cls.server.cut_done=False
        cls.server.headers_waiting=threading.Event()
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True,name='https-fixture')
        cls.thread.start()
        cls.base=f'https://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)
        cls.workspace.cleanup()

    def setUp(self):
        self.folder=Path(self.enterContext(tempfile.TemporaryDirectory(prefix='fetchvolt-transfer-')))
        self.records=self.folder/'records'
        self.records.mkdir()
        self.target=self.folder/'file.bin'
        self.enterContext(patch.object(recovery,'directory',return_value=self.records))
        self.enterContext(patch.object(engine,'TLS',ssl.create_default_context(cafile=self.cert)))
        self.enterContext(patch.object(engine,'CHUNK',65536))
        self.scanner=self.enterContext(patch.object(engine,'scan_file'))
        with self.server.state_lock:
            self.server.requests.clear()
            self.server.cut_done=False
            self.server.headers_waiting.clear()

    def transfer(self, path='/file', links=None, **options):
        return engine.download(self.base+path,self.target,links or {'path-A':0,'path-B':0},lambda *_:None,expected_sha256=DIGEST,**options)

    def assert_intact(self, totals):
        self.assertEqual(hashlib.sha256(self.target.read_bytes()).hexdigest(),DIGEST)
        self.assertEqual(sum(totals.values()),len(BODY))
        self.assertIn(b'ZoneId=3',Path(str(self.target)+':Zone.Identifier').read_bytes())
        self.assertFalse(list(self.folder.glob('.net-booster-*.part')))

    def test_single_stream_real_tls(self):
        _,totals=self.transfer(links={'path-A':0})
        self.assert_intact(totals)
        self.scanner.assert_called_once()

    @patch.object(engine,'STREAMS_PER_LINK',1)
    def test_seven_logical_workers_real_tls(self):
        _,totals=self.transfer('/slow',{f'path-{i}':0 for i in range(7)})
        self.assert_intact(totals)
        self.assertTrue(all(totals.values()))

    def test_server_ignores_ranges_falls_back(self):
        _,totals=self.transfer('/ignore-range')
        self.assert_intact(totals)
        self.assertEqual(totals['path-B'],0)

    def test_redirect_real_tls(self):
        self.assert_intact(self.transfer('/redirect')[1])

    def test_socket_disconnect_retries_other_path(self):
        self.assert_intact(self.transfer('/cut-once')[1])
        self.assertTrue(self.server.cut_done)

    def test_truncated_single_stream_preserves_old_destination(self):
        self.target.write_bytes(b'existing')
        with self.assertRaises(OSError):
            self.transfer('/truncate',{'path-A':0})
        self.assertEqual(self.target.read_bytes(),b'existing')
        self.assertFalse(list(self.folder.glob('.net-booster-*.part')))
        self.scanner.assert_not_called()

    def test_wrong_range_rejected_without_publish(self):
        with self.assertRaises(ValueError):
            self.transfer('/bad-range')
        self.assertFalse(self.target.exists())
        self.scanner.assert_not_called()

    def test_changed_etag_rejected_without_publish(self):
        with self.assertRaises(ValueError):
            self.transfer('/changed-etag')
        self.assertFalse(self.target.exists())
        self.scanner.assert_not_called()

    def deadline_case(self,path,argument):
        request=engine.request
        def bounded(*args,**kwargs):
            kwargs[argument]=.2
            return request(*args,**kwargs)
        start=time.monotonic()
        with patch.object(engine,'request',side_effect=bounded),self.assertRaises((OSError,ValueError)):
            self.transfer(path,{'path-A':0})
        self.assertLess(time.monotonic()-start,4)
        self.assertFalse(self.target.exists())

    def test_stalled_headers_obey_deadline(self):
        self.deadline_case('/stall-headers','header_timeout')

    def test_stalled_body_obeys_deadline(self):
        self.deadline_case('/stall-body','response_timeout')

    def test_pause_resume_over_active_sockets(self):
        control=engine.LiveLinks({'path-A':0})
        paused=threading.Event()
        progress=[]
        def report(totals,size):
            progress.append(sum(totals.values()))
            if not paused.is_set():
                self.assertTrue(control.pause())
                paused.set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            job=pool.submit(engine.download,self.base+'/slow',self.target,{'path-A':0},report,
                            live_links=control,expected_sha256=DIGEST)
            try:
                self.assertTrue(paused.wait(4))
                before=progress[:]
                time.sleep(.3)
                self.assertEqual(progress,before)
                self.assertFalse(self.target.exists())
            finally:
                control.resume()
            self.assert_intact(job.result(timeout=12)[1])

    def test_new_logical_path_joins_running_transfer(self):
        control=engine.LiveLinks({'path-A':0})
        def report(*_):
            self.assertTrue(control.update({'path-A':0,'path-B':0}))
        _,totals=engine.download(self.base+'/slow',self.target,{'path-A':0},report,
                                live_links=control,expected_sha256=DIGEST)
        self.assert_intact(totals)
        self.assertGreater(totals.get('path-B',0),0)

    def test_save_close_and_resume_skips_verified_ranges(self):
        control=engine.LiveLinks({'path-A':0})
        identifier=uuid4().hex
        def stop(*_):
            control.cancel(preserve=True)
        with self.assertRaises(engine.DownloadStopped):
            engine.download(self.base+'/slow',self.target,{'path-A':0},stop,
                            live_links=control,recovery_id=identifier,expected_sha256=DIGEST)
        record=recovery.load(identifier)
        complete=record.verified()
        self.assertTrue(complete)
        self.assertFalse(self.target.exists())
        with self.server.state_lock:
            self.server.requests.clear()
        _,totals=self.transfer('/slow',recovery_id=identifier)
        self.assert_intact(totals)
        self.assertGreater(totals['Recovered'],0)
        requested={low for _,low,_,is_range in self.server.requests if is_range}
        self.assertFalse(complete & requested)

    def test_cancel_active_socket_discards_checkpoint(self):
        control=engine.LiveLinks({'path-A':0})
        identifier=uuid4().hex
        with self.assertRaises(engine.DownloadCancelled):
            engine.download(self.base+'/slow',self.target,{'path-A':0},lambda *_:control.cancel(),
                            live_links=control,recovery_id=identifier)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.folder.glob('.net-booster-*.part')))
        self.assertFalse(list(self.records.glob('*.json')))

    def test_scanner_unavailable_blocks_actual_download(self):
        self.scanner.side_effect=ScanError('simulated unavailable scanner')
        with self.assertRaises(ScanError):
            self.transfer()
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.folder.glob('.net-booster-*.part')))

    def test_two_concurrent_files_use_real_sockets(self):
        def task(number):
            target=self.folder/f'parallel-{number}.bin'
            result=engine.download(self.base+'/slow',target,{'path-A':0,'path-B':0},lambda *_:None,
                                   expected_sha256=DIGEST)
            return target,result
        with ThreadPoolExecutor(max_workers=2) as pool:
            for target,result in pool.map(task,range(2)):
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),DIGEST)
                self.assertEqual(sum(result[1].values()),len(BODY))


    def test_process_kill_recovers_durable_ranges(self):
        identifier=uuid4().hex
        child_code="""import os,sys,ssl; import tests; import net_booster as e,recovery; from pathlib import Path
recovery.directory=lambda:Path(sys.argv[1]);e.TLS=ssl.create_default_context(cafile=sys.argv[2]);e.CHUNK=65536
e.download(sys.argv[3],Path(sys.argv[4]),{'path-A':0},lambda *_:os._exit(73),live_links=e.LiveLinks({'path-A':0}),recovery_id=sys.argv[5])
"""
        run=subprocess.run([sys.executable,'-c',child_code,str(self.records),str(self.cert),
                            self.base+'/slow',str(self.target),identifier],capture_output=True,timeout=10)
        self.assertEqual(run.returncode,73,run.stderr.decode(errors='replace'))
        record=recovery.load(identifier)
        self.assertTrue(record.verified())
        self.assertFalse(self.target.exists())
        # Fresh process state reads a durable record; no in-memory progress survives.
        self.assert_intact(self.transfer('/slow',recovery_id=identifier)[1])
        self.assertFalse(record.path.exists())

    def test_tls_certificate_is_rejected_without_test_trust(self):
        with patch.object(engine,'TLS',ssl.create_default_context()),self.assertRaises(ssl.SSLCertVerificationError):
            self.transfer(links={'path-A':0})
        self.assertFalse(self.target.exists())
        self.scanner.assert_not_called()

    def test_wrong_expected_checksum_blocks_publication(self):
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            engine.download(self.base+'/file',self.target,{'path-A':0},lambda *_:None,
                            expected_sha256='0'*64)
        self.assertFalse(self.target.exists())
        self.scanner.assert_not_called()

    def test_destination_collision_does_not_overwrite(self):
        self.target.write_bytes(b'keep this file')
        with self.assertRaises(FileExistsError):
            self.transfer(overwrite=False)
        self.assertEqual(self.target.read_bytes(),b'keep this file')

    def test_low_disk_space_blocks_staging(self):
        usage=__import__('collections').namedtuple('Usage','total used free')(100,99,1)
        with patch.object(engine.shutil,'disk_usage',return_value=usage),self.assertRaises(OSError):
            self.transfer()
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.folder.glob('.net-booster-*.part')))
        self.scanner.assert_not_called()

    def test_repeated_transfers_release_handles_and_threads(self):
        import gc
        import psutil
        process=psutil.Process()
        gc.collect()
        handles=process.num_handles()
        threads=threading.active_count()
        rss=process.memory_info().rss
        for _ in range(20):
            self.assert_intact(self.transfer()[1])
            self.target.unlink()
            self.scanner.reset_mock()
        time.sleep(.15)
        gc.collect()
        self.assertLessEqual(process.num_handles()-handles,12)
        self.assertLessEqual(threading.active_count()-threads,2)
        self.assertLess(process.memory_info().rss-rss,48*1024*1024)

    def test_desktop_save_close_drains_real_transfer_worker(self):
        import desktop
        from unittest.mock import Mock
        with patch.object(desktop,'History'):
            api=desktop.Desktop(restore=False)
        control=engine.LiveLinks({'path-A':0})
        ready=threading.Event()
        closed=threading.Event()
        errors=[]
        identifier=uuid4().hex
        api._window=Mock()
        api._window.destroy.side_effect=closed.set
        api._jobs[1]={'view':{'state':'running'},'selection':control,'recovery_id':identifier}
        def work():
            try:
                engine.download(self.base+'/slow',self.target,{'path-A':0},lambda *_:ready.set(),
                                live_links=control,recovery_id=identifier)
            except engine.DownloadStopped:
                pass
            except Exception as error:
                errors.append(error)
        worker=threading.Thread(target=work,name='real-close-transfer')
        api._threads.append(worker)
        worker.start()
        try:
            self.assertTrue(ready.wait(4))
            self.assertIsNone(api.close_app('save'))
            self.assertTrue(closed.wait(4))
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors,errors)
            self.assertTrue(recovery.load(identifier).verified())
        finally:
            control.cancel(preserve=True)
            worker.join(5)

    @unittest.expectedFailure
    def test_cancel_pending_headers_returns_within_250ms(self):
        """Known issue: initial request is not attached to LiveLinks yet."""
        control=engine.LiveLinks({'path-A':0})
        with ThreadPoolExecutor(max_workers=1) as pool:
            job=pool.submit(engine.download,self.base+'/stall-headers',self.target,
                            {'path-A':0},lambda *_:None,live_links=control)
            try:
                self.assertTrue(self.server.headers_waiting.wait(3))
            finally:
                started=time.monotonic()
                control.cancel(preserve=True)
            with self.assertRaises(engine.DownloadStopped):
                job.result(timeout=4)
            elapsed=time.monotonic()-started
        self.assertFalse(self.target.exists())
        self.assertLess(elapsed,.25,'Cancel waits for initial response headers')

    @unittest.skipUnless(os.environ.get('FETCHVOLT_REAL_DEFENDER_TEST')=='1',
                         'Opt in to a real Defender scan of the harmless local payload')
    def test_real_defender_scans_socket_download(self):
        from windows_security import scan_file
        self.scanner.side_effect=scan_file
        self.assert_intact(self.transfer()[1])

if __name__ == '__main__':
    unittest.main()
