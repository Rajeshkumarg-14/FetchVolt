import base64
from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import cli
import updater


def manifest_for(files=None):
    files = files or {name: b'new-' + name.encode() for name in updater.FILES}
    return {'format':1,'version':'2.7.0','url':'https://github.com/Rajeshkumarg-14/fetchvolt-site/releases/download/v2.7.0/FetchVolt-Setup-2.7.0.zip',
            'bytes':1,'sha256':'a'*64,'files':{name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()}}


def signed(value):
    payload=json.dumps(value,separators=(',',':')).encode()
    script="""$p=[Console]::In.ReadToEnd();$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider(3072);$rsa.PersistKeyInCsp=$false;try{$data=[Convert]::FromBase64String($p);@{key=$rsa.ToXmlString($false);payload=$p;signature=[Convert]::ToBase64String($rsa.SignData($data,'SHA256'));algorithm='rsa-pkcs1v15-sha256'}|ConvertTo-Json -Compress}finally{$rsa.Dispose()}"""
    result=subprocess.run([str(updater.powershell()),'-NoProfile','-NonInteractive','-Command',script],input=base64.b64encode(payload),capture_output=True,timeout=20,check=True)
    output=json.loads(result.stdout)
    key=output.pop('key')
    return key,json.dumps(output).encode()


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.key,cls.raw=signed(manifest_for())
    def test_real_windows_signature_roundtrip(self):
        with patch.object(updater,'PUBLIC_KEY_XML',self.key):self.assertEqual(updater.parse_manifest(self.raw)['version'],'2.7.0')
    def test_tampered_signed_payload_rejected(self):
        wrapper=json.loads(self.raw);wrapper['payload']=base64.b64encode(base64.b64decode(wrapper['payload']).replace(b'2.7.0',b'2.8.0')).decode()
        with patch.object(updater,'PUBLIC_KEY_XML',self.key),self.assertRaises(ValueError):updater.parse_manifest(json.dumps(wrapper).encode())
    def test_untrusted_publisher_rejected(self):
        with self.assertRaises(ValueError):updater.parse_manifest(self.raw)
    def test_signature_timeout_fails_closed(self):
        with patch.object(updater.subprocess,'run',side_effect=subprocess.TimeoutExpired('verify',15)),self.assertRaises(subprocess.TimeoutExpired):updater.parse_manifest(self.raw)
    def test_duplicate_wrapper_fields_rejected_before_verification(self):
        with patch.object(updater,'verify_signature') as verify,self.assertRaises(ValueError):updater.parse_manifest(b'{"algorithm":1,"algorithm":2}')
        verify.assert_not_called()
    def test_schema_url_size_and_version_rejections(self):
        for field,value in [('url','https://evil.example/setup.zip'),('url','https://github.com/other/repo/a.zip'),('bytes',True),('bytes',updater.MAX_ZIP+1),('version','2.7.0;cmd'),('version','02.7.0'),('version','99999.0.0'),('sha256','g'*64),('format',True),('files',{'../x':{}})]:
            with self.subTest(field=field,value=value):
                data=manifest_for();data[field]=value
                wrapper={'algorithm':'rsa-pkcs1v15-sha256','payload':base64.b64encode(json.dumps(data).encode()).decode(),'signature':base64.b64encode(b'x'*384).decode()}
                with patch.object(updater,'verify_signature'),self.assertRaises((ValueError,TypeError)):updater.parse_manifest(json.dumps(wrapper).encode())
    def test_metadata_envelope_and_payload_size_limits(self):
        for raw in [b'x'*40961,b'[]',b'{"algorithm":"other","payload":"","signature":""}']:
            with self.subTest(raw=raw[:20]),self.assertRaises((ValueError,TypeError)):updater.parse_manifest(raw)
    def test_source_checkout_cannot_self_replace(self):
        with patch.object(updater,'install_directory',return_value=Path(tempfile.gettempdir())),patch.object(updater,'is_packaged',return_value=False),self.assertRaisesRegex(ValueError,'managed'):updater.prepare(manifest_for(),self.raw)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.files={name:b'new-'+name.encode() for name in updater.FILES}
    def archive(self,extra=None):
        path=self.root/'update.zip'
        with zipfile.ZipFile(path,'w') as archive:
            for name,data in self.files.items():archive.writestr(name,data)
            if extra:archive.writestr(*extra)
        manifest=manifest_for(self.files);manifest['bytes']=path.stat().st_size;manifest['sha256']=updater.digest_file(path)
        folder=self.root/'stage';folder.mkdir(exist_ok=True)
        return path,folder,manifest
    def test_verified_files_receive_mark_of_web_and_scan(self):
        path,folder,manifest=self.archive()
        with patch('windows_security.scan_file') as scanner:updater.unpack(path,folder,manifest)
        self.assertEqual(scanner.call_count,len(self.files))
        for name,data in self.files.items():
            self.assertEqual((folder/name).read_bytes(),data)
            self.assertIn('ZoneId=3',Path(str(folder/name)+':Zone.Identifier').read_text())
    def test_archive_corruption_blocked_before_extraction(self):
        path,folder,manifest=self.archive();path.write_bytes(path.read_bytes()+b'tamper')
        with patch('windows_security.scan_file') as scanner,self.assertRaises(ValueError):updater.unpack(path,folder,manifest)
        scanner.assert_not_called();self.assertEqual(list(folder.iterdir()),[])
    def test_traversal_unknown_and_duplicate_entries_rejected(self):
        for name in ['../outside','folder/FetchVolt.exe','C:/outside','FetchVolt.exe']:
            with self.subTest(name=name):
                path,folder,manifest=self.archive((name,b'bad'))
                with self.assertRaises(ValueError):updater.unpack(path,folder,manifest)
                self.assertEqual(list(folder.iterdir()),[])
    def test_bad_per_file_hash_blocks_scan(self):
        path,folder,manifest=self.archive()
        first=next(iter(self.files));manifest['files'][first]['sha256']='0'*64
        with patch('windows_security.scan_file') as scanner,self.assertRaises(ValueError):updater.unpack(path,folder,manifest)
        scanner.assert_not_called()
    def test_scanner_failure_cannot_be_ignored(self):
        path,folder,manifest=self.archive()
        with patch('windows_security.scan_file',side_effect=OSError('unavailable')),self.assertRaises(OSError):updater.unpack(path,folder,manifest)
    def test_symlink_entry_rejected(self):
        path,folder,manifest=self.archive()
        infos=[]
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():infos.append((item,archive.read(item)))
        infos[0][0].create_system=3;infos[0][0].external_attr=0o120777<<16
        with zipfile.ZipFile(path,'w') as archive:
            for item,data in infos:archive.writestr(item,data)
        manifest['bytes']=path.stat().st_size;manifest['sha256']=updater.digest_file(path)
        with self.assertRaises(ValueError):updater.unpack(path,folder,manifest)


class CliTests(unittest.TestCase):
    def test_version_and_help_do_not_need_gui(self):
        for arg in ['--version','--help']:
            result=subprocess.run([__import__('sys').executable,'app/desktop.py',arg],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('FetchVolt',result.stdout)
    def test_check_only_does_not_prepare_update(self):
        with patch.object(updater,'check',return_value=(manifest_for(),b'raw')),patch.object(updater,'prepare') as prepare,redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['update','--check','--json']),0)
        prepare.assert_not_called();self.assertTrue(json.loads(output.getvalue())['available'])
    def test_no_downgrade_or_reinstall(self):
        data=manifest_for();data['version']='1.0.0'
        with patch.object(updater,'check',return_value=(data,b'raw')),patch.object(updater,'prepare') as prepare,redirect_stdout(io.StringIO()):self.assertEqual(cli.main(['update']),0)
        prepare.assert_not_called()
    def test_unknown_arguments_fail_without_gui(self):
        result=subprocess.run([__import__('sys').executable,'app/desktop.py','update','--force-unsigned'],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,2)


class WorkerTests(unittest.TestCase):
    def run_worker(self,fail=False):
        with tempfile.TemporaryDirectory() as temporary:
            install=Path(temporary)/'Install';install.mkdir();stage=install/'.fetchvolt-update-unit';stage.mkdir()
            files={name:b'new-'+name.encode() for name in updater.FILES}
            data=manifest_for(files);key,raw=signed(data)
            for name,body in files.items():(stage/name).write_bytes(body)
            (stage/'update.json').write_bytes(raw);(stage/'lock-path.txt').write_text(str(install/'desktop.lock'))
            (install/'Net Booster.exe').write_bytes(b'old-exe');(install/'Uninstall-NetBooster.ps1').write_bytes(b'old-uninstall')
            if fail:(install/'LICENSE').mkdir()
            source=Path('scripts/Apply-Update.ps1').read_text('utf-8')
            # Isolated filesystem harness; no bypass flags exist in production.
            source=source.replace("$install=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\\Net Booster'", "$install='"+str(install).replace("'","''")+"'")
            source=source.replace(" try{$null=New-ItemProperty -LiteralPath $registry -Name DisplayVersion -Value $manifest.version -PropertyType String -Force}catch{}", '')
            source=source.replace('$current=[Diagnostics.FileVersionInfo]::GetVersionInfo($exe)', "$current=[PSCustomObject]@{ProductName='FetchVolt';FileVersion='2.6.0.0'}")
            source=source.replace("$new=[Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $stage 'FetchVolt.exe'))", "$new=[PSCustomObject]@{FileVersion='2.7.0.0'}")
            (stage/'apply.ps1').write_text(source.replace('__PUBLIC_KEY_XML__',key),encoding='utf-8')
            pwsh=Path(__import__('shutil').which('pwsh.exe'))
            run=subprocess.run([str(pwsh),'-NoProfile','-File',str(stage/'apply.ps1'),'-WaitPid','99999999'],capture_output=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr.decode(errors='replace'))
            result=json.loads((install/'.update-result.json').read_text())
            if fail:
                self.assertEqual(result['state'],'failed');self.assertEqual((install/'Net Booster.exe').read_bytes(),b'old-exe');self.assertEqual((install/'Uninstall-NetBooster.ps1').read_bytes(),b'old-uninstall')
            else:
                self.assertEqual(result['state'],'complete');self.assertEqual((install/'Net Booster.exe').read_bytes(),files['FetchVolt.exe'])
    def test_real_worker_applies_verified_files(self):self.run_worker()
    def test_real_worker_rolls_back_partial_replacement(self):self.run_worker(True)


class UpdateConcurrencyTests(unittest.TestCase):
    def test_pending_live_worker_blocks_a_second_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            install=Path(temporary)
            (install/'.update-result.json').write_text(json.dumps({'state':'pending','pid':__import__('os').getpid()}))
            with patch.object(updater,'install_directory',return_value=install),patch.object(updater,'is_packaged',return_value=True),patch.object(updater,'executable',return_value=install/'Net Booster.exe'),patch.object(updater,'_prepare') as apply:
                with self.assertRaisesRegex(ValueError,'already'):updater.prepare({},b'')
                apply.assert_not_called()
    def test_stale_worker_result_can_be_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            install=Path(temporary)
            (install/'.update-result.json').write_text(json.dumps({'state':'pending','pid':99999999}))
            with patch.object(updater,'install_directory',return_value=install),patch.object(updater,'is_packaged',return_value=True),patch.object(updater,'executable',return_value=install/'Net Booster.exe'),patch.object(updater,'_prepare',return_value='queued') as apply:
                self.assertEqual(updater.prepare({},b''),'queued');apply.assert_called_once()
