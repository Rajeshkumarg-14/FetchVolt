import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from desktop import Desktop


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('desktop.History'))
        self.api = Desktop(restore=False)
        self.api._window = Mock()
        self.api._rows = [{'index': 13, 'name': 'Wi-Fi', 'gateway': True, 'status': 'Up'}]
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def enqueue(self, filename, priority='normal'):
        self.api._window.create_file_dialog.return_value = str(self.folder / filename)
        return self.api.start('https://example.com/' + filename, [13], priority)

    def test_priority_orders_waiting_jobs_and_preserves_fifo_for_ties(self):
        low = self.enqueue('low.zip', 'low')
        first = self.enqueue('first.zip', 'high')
        second = self.enqueue('second.zip', 'high')
        self.assertEqual(self.api._next_job()['view']['id'], first)
        self.api._jobs[first]['view']['state'] = 'running'
        self.assertFalse(self.api.change_priority(first, 'low'))
        self.assertEqual(self.api._next_job()['view']['id'], second)
        self.assertTrue(self.api.change_priority(second, 'low'))
        self.assertEqual(self.api._next_job()['view']['id'], low)

    def test_duplicate_destination_is_rejected_until_waiting_job_is_removed(self):
        first = self.enqueue('same.zip')
        self.assertIn('already using', self.enqueue('SAME.zip'))
        self.assertTrue(self.api.cancel_waiting(first))
        self.assertIsInstance(self.enqueue('same.zip'), int)

    def test_invalid_adapter_or_url_never_opens_save_dialog(self):
        self.assertIsInstance(self.api.start('https://example.com/file', [99], 'normal'), str)
        self.assertIsInstance(self.api.start('http://example.com/file', [13], 'normal'), str)
        self.assertIsInstance(self.api.start('https://example.com/file', [13, 13], 'normal'), str)
        self.api._window.create_file_dialog.assert_not_called()

    def test_accepts_seven_distinct_connections_and_rejects_eight(self):
        self.api._rows = [
            {'index': index, 'name': f'Adapter {index}', 'gateway': True, 'status': 'Up'}
            for index in range(1, 9)
        ]
        self.api._window.create_file_dialog.return_value = str(self.folder / 'file.zip')
        self.assertIsInstance(self.api.start('https://example.test/file', list(range(1, 9)), 'normal'), str)
        self.api._window.create_file_dialog.assert_not_called()
        identifier = self.api.start('https://example.test/file', list(range(1, 8)), 'normal')
        self.assertIsInstance(identifier, int)
        self.assertEqual(len(self.api._jobs[identifier]['links']), 7)

    def test_active_job_can_pause_resume_and_change_connections(self):
        identifier = self.enqueue('active.zip')
        job = self.api._jobs[identifier]
        job['view']['state'] = 'running'
        job['selection'].set_mode('range')
        self.api._rows.append({'index': 2, 'name': 'USB', 'gateway': True, 'status': 'Up'})
        self.assertIsNone(self.api.control_download(identifier, 'pause'))
        self.assertEqual(self.api.state()['jobs'][0]['state'], 'paused')
        self.assertIsNone(self.api.apply_connections(identifier, [13, 2]))
        self.assertEqual(job['selection'].snapshot()[2], {'Wi-Fi': 13, 'USB': 2})
        self.assertIsNone(self.api.control_download(identifier, 'resume'))
        self.assertEqual(self.api.state()['jobs'][0]['state'], 'running')
        self.assertIsNone(self.api.control_download(identifier, 'cancel'))
        self.assertTrue(job['selection'].status()['cancelled'])

    def test_turbo_uses_all_adapters_and_holds_other_range_downloads(self):
        first = self.enqueue('first.zip')
        second = self.enqueue('second.zip')
        self.api._rows.append({'index': 49, 'name': 'USB', 'gateway': True, 'status': 'Up'})
        for identifier in (first, second):
            self.api._jobs[identifier]['view']['state'] = 'running'
            self.api._jobs[identifier]['selection'].set_mode('range')
        self.assertIsNone(self.api.set_turbo(second, True))
        jobs = self.api.state()['jobs']
        self.assertEqual(jobs[0]['state'], 'held')
        self.assertTrue(jobs[1]['turbo'])
        self.assertEqual(jobs[1]['selectedAdapters'], ['Wi-Fi', 'USB'])
        self.assertIn('Turn off Turbo', self.api.control_download(second, 'pause'))
        self.assertIsNone(self.api.set_turbo(second, False))
        self.assertTrue(all(job['state'] == 'running' for job in self.api.state()['jobs']))

    def test_waiting_turbo_file_is_scheduled_ahead_of_held_downloads(self):
        identifiers = [self.enqueue(f'{index}.zip') for index in range(3)]
        for identifier in identifiers[:2]:
            job = self.api._jobs[identifier]
            job['view']['state'] = 'running'
            job['selection'].set_mode('range')
        self.assertIsNone(self.api.set_turbo(identifiers[2], True))
        self.assertEqual(self.api._next_job()['view']['id'], identifiers[2])
        self.api._jobs[identifiers[2]]['view']['state'] = 'running'
        self.assertIsNone(self.api._next_job())
        self.api._rebalance()
        self.assertIsNone(self.api.set_turbo(identifiers[2], False))
        self.assertEqual(sum(not job['selection'].status()['held'] for job in self.api._jobs.values()), 2)

    def test_turbo_does_not_resume_a_user_paused_file(self):
        identifier = self.enqueue('paused.zip')
        job = self.api._jobs[identifier]
        job['view']['state'] = 'running'
        job['selection'].set_mode('range')
        job['selection'].pause()
        self.assertIn('Resume', self.api.set_turbo(identifier, True))
        self.assertIsNone(self.api._turbo_id)
        self.assertTrue(job['selection'].status()['paused'])

    def test_turbo_rejects_another_active_single_stream(self):
        first = self.enqueue('first.zip')
        second = self.enqueue('second.zip')
        for identifier in (first, second):
            self.api._jobs[identifier]['view']['state'] = 'running'
        self.api._jobs[first]['selection'].set_mode('single')
        self.api._jobs[second]['selection'].set_mode('range')
        self.assertIsInstance(self.api.set_turbo(second, True), str)
        self.assertIsNone(self.api._turbo_id)

    def test_removing_waiting_turbo_releases_held_jobs(self):
        first = self.enqueue('first.zip')
        second = self.enqueue('second.zip')
        job = self.api._jobs[first]
        job['view']['state'] = 'running'
        job['selection'].set_mode('range')
        self.assertIsNone(self.api.set_turbo(second, True))
        self.assertTrue(job['selection'].status()['held'])
        self.assertTrue(self.api.cancel_waiting(second))
        self.assertIsNone(self.api._turbo_id)
        self.assertFalse(job['selection'].status()['held'])

    def test_save_and_close_stops_workers_but_preserves_progress(self):
        from net_booster import DownloadStopped
        from threading import Event
        identifier = self.enqueue('close.zip')
        job = self.api._jobs[identifier]
        job['view']['state'] = 'running'
        job['selection'].set_mode('range')
        closed = Event()
        self.api._window.destroy.side_effect = closed.set
        self.assertIsNone(self.api.close_app('save'))
        self.assertTrue(closed.wait(3))
        self.assertTrue(self.api._allow_close)
        self.assertIsNone(self.api._next_job())
        with self.assertRaises(DownloadStopped):
            job['selection'].check()

    def test_cancel_and_close_cancels_active_file(self):
        from net_booster import DownloadCancelled
        from threading import Event
        identifier = self.enqueue('cancel-close.zip')
        job = self.api._jobs[identifier]
        job['view']['state'] = 'running'
        closed = Event()
        self.api._window.destroy.side_effect = closed.set
        self.assertIsNone(self.api.close_app('cancel'))
        self.assertTrue(closed.wait(3))
        with self.assertRaises(DownloadCancelled):
            job['selection'].check()

    def test_window_close_requests_a_choice_while_busy(self):
        from threading import Event
        self.enqueue('waiting.zip')
        prompted = Event()
        self.api._window.evaluate_js.side_effect = lambda *_: prompted.set()
        self.assertFalse(self.api._on_closing())
        self.assertTrue(prompted.wait(3))
        self.api._allow_close = True
        self.assertTrue(self.api._on_closing())

    def test_native_traffic_samples_update_rate_and_detect_resets(self):
        from threading import Thread
        import time
        samples = [
            (1.0, {'Wi-Fi': {'rx': 100, 'tx': 50}}),
            (2.0, {'Wi-Fi': {'rx': 1000100, 'tx': 500050}}),
            (3.0, {'Wi-Fi': {'rx': 10, 'tx': 2}}),
        ]
        for row in self.api._rows:
            row.update(rx=0, tx=0)
        events = [__import__('threading').Event() for _ in samples]
        def next_sample():
            index = next_sample.index
            next_sample.index += 1
            if index == len(samples):
                self.api._shutdown_requested = True
                return samples[-1]
            events[index].set()
            return samples[index]
        next_sample.index = 0
        with patch('desktop.traffic_snapshot', side_effect=next_sample):
            worker = Thread(target=self.api._traffic_monitor)
            worker.start()
            try:
                self.assertTrue(events[1].wait(3))
                time.sleep(.03)
                with self.api._lock:
                    row = self.api._rows[0].copy()
                self.assertEqual(row['rxRate'], 8.0)
                self.assertEqual(row['txRate'], 4.0)
                self.assertTrue(events[2].wait(3))
                time.sleep(.03)
                with self.api._lock:
                    self.assertIsNone(self.api._rows[0]['rxRate'])
            finally:
                self.api._shutdown_requested = True
                worker.join(3)

    def test_transfer_settings_validate_before_writing(self):
        with patch('appearance.winreg.CreateKey') as create, patch('appearance.winreg.SetValueEx') as save:
            with self.assertRaises(ValueError):
                self.api.set_transfer_preference('layout', 'unknown')
            create.assert_not_called()
            self.api.set_transfer_preference('layout', 'vertical')
            self.assertEqual(save.call_args.args[1], 'TransferLayout')
            self.assertEqual(save.call_args.args[-1], 'vertical')

    def test_old_install_defaults_to_auto_layout_and_system_motion(self):
        with patch('appearance.winreg.OpenKey', side_effect=FileNotFoundError):
            self.assertEqual(self.api.preferences(), {'theme': 'system', 'displayName': 'My workspace', 'layout': 'auto', 'motion': 'system', 'speed': 'mbps', 'surface': 'solid'})

    def test_display_name_validates_before_writing_and_normalizes(self):
        with patch('appearance.winreg.CreateKey') as create, patch('appearance.winreg.SetValueEx') as save:
            for value in ('', 'x' * 41, 'a\nb', 'name\u202e', None, True):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.api.set_display_name(value)
            create.assert_not_called()
            self.assertEqual(self.api.set_display_name('  New User  '), 'New User')
            self.assertEqual(save.call_args.args[1], 'DisplayName')
            self.assertEqual(save.call_args.args[-1], 'New User')

    def test_job_progress_and_history_are_separate(self):
        first = self.enqueue('first.zip')
        second = self.enqueue('second.zip')

        def fake_download(url, target, links, report, **options):
            report({'Wi-Fi': 128}, 256)
            state = self.api.state()['jobs']
            self.assertEqual(state[0]['active'], ['Wi-Fi'])
            self.assertEqual(state[1]['totals'], {'Wi-Fi': 0})
            return 1.5, {'Wi-Fi': 256}

        self.api._jobs[first]['view']['state'] = 'running'
        with patch('desktop.download', fake_download):
            self.api._run(self.api._jobs[first])
        jobs = self.api.state()['jobs']
        self.assertEqual(jobs[0]['state'], 'saved')
        self.assertEqual(jobs[1]['id'], second)
        self.api._history.add.assert_called_once()


if __name__ == '__main__':
    unittest.main()
