import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / 'AIAgents.dynamiclakeplugin' / 'ai-agents-monitor.py'
spec = importlib.util.spec_from_file_location('ai_agents_monitor', PLUGIN)
monitor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = monitor
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def test_opencode_reads_session_and_phase_without_content(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'opencode.db'
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            with sqlite3.connect(database) as connection:
                connection.executescript('''
                    CREATE TABLE session (id TEXT, directory TEXT, title TEXT, time_updated INTEGER, time_archived INTEGER);
                    CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT);
                    CREATE TABLE part (id TEXT, message_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT);
                ''')
                connection.execute('INSERT INTO session VALUES (?,?,?,?,NULL)', ('ses_1', '/tmp/sample-project', 'Task', now_ms))
                connection.execute('INSERT INTO message VALUES (?,?,?,?,?)', ('msg_1', 'ses_1', now_ms, now_ms, json.dumps({'role': 'assistant', 'time': {'created': now_ms}, 'tokens': {'total': 42, 'input': 40, 'output': 2}})))
                connection.execute('INSERT INTO part VALUES (?,?,?,?,?)', ('prt_1', 'msg_1', now_ms, now_ms, json.dumps({'type': 'tool', 'tool': 'Bash', 'state': {'status': 'running'}, 'secret': 'must-not-publish'})))
            with patch.dict(os.environ, {'OPENCODE_DB': str(database)}):
                state = monitor.load_opencode_state()
            self.assertEqual((state.session_id, state.project_name, state.phase, state.total_tokens), ('ses_1', 'sample-project', 'tool', 42))
            self.assertNotIn('must-not-publish', json.dumps(monitor.activity_message(monitor.OPENCODE, state, 'create')))

    def test_logo_setting_changes_both_surfaces(self):
        state = monitor.AgentState('ses_1', 'Task', 'project', None, 'thinking', 'Thinking', None, 0, 0, 0, datetime.now(timezone.utc))
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'settings.json'
            with patch.dict(os.environ, {'DYNAMICLAKE_PLUGIN_SETTINGS_PATH': str(settings)}, clear=False):
                settings.write_text(json.dumps({'values': {'showAgentLogos': False}}))
                message = monitor.activity_message(monitor.CLAUDE, state, 'create')
                self.assertEqual(message['surfaces']['compactLiveActivity']['leftSlot']['source'], 'sfSymbol')
                self.assertEqual(message['surfaces']['extraLiveActivity']['leftSlot'], monitor.source_logo(monitor.CLAUDE))
                self.assertNotIn('rightSlot', message['surfaces']['extraLiveActivity'])
                settings.write_text(json.dumps({'values': {'showAgentLogos': True}}))
                message = monitor.activity_message(monitor.CLAUDE, state, 'update')
                for surface in ('compactLiveActivity', 'extraLiveActivity', 'sneakPeek'):
                    slot = message['surfaces'][surface]['leftSlot']
                    self.assertEqual((slot['source'], slot['mimeType']), ('inlineData', 'image/png'))
                    self.assertLess(len(slot['base64Data']), 64_000)

    def test_completed_keeps_logo_left_and_checkmark_right(self):
        state = monitor.AgentState('ses_1', 'Task', 'project', None, 'completed', 'Complete', None, 0, 0, 0, datetime.now(timezone.utc))
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'settings.json'
            with patch.dict(os.environ, {'DYNAMICLAKE_PLUGIN_SETTINGS_PATH': str(settings)}):
                settings.write_text(json.dumps({'values': {'showAgentLogos': False}}))
                surfaces = monitor.activity_message(monitor.OPENCODE, state, 'create')['surfaces']
                self.assertEqual(surfaces['compactLiveActivity']['rightSlot']['type'], 'progress')
                self.assertEqual(surfaces['extraLiveActivity']['leftSlot'], monitor.source_logo(monitor.OPENCODE))
                self.assertNotIn('rightSlot', surfaces['sneakPeek'])

                settings.write_text(json.dumps({'values': {'showAgentLogos': True}}))
                surfaces = monitor.activity_message(monitor.OPENCODE, state, 'update')['surfaces']
                for surface in ('compactLiveActivity', 'sneakPeek'):
                    self.assertEqual(surfaces[surface]['leftSlot'], monitor.source_logo(monitor.OPENCODE))
                    self.assertEqual(surfaces[surface]['rightSlot']['systemImage'], 'checkmark.circle.fill')
                    self.assertEqual(surfaces[surface]['rightSlot']['tint'], 'green')
                self.assertEqual(surfaces['extraLiveActivity']['leftSlot'], monitor.source_logo(monitor.OPENCODE))
                self.assertNotIn('rightSlot', surfaces['extraLiveActivity'])

    def test_minimized_identity_for_every_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'settings.json'
            with patch.dict(os.environ, {'DYNAMICLAKE_PLUGIN_SETTINGS_PATH': str(settings)}):
                for logos in (False, True):
                    settings.write_text(json.dumps({'values': {'showAgentLogos': logos}}))
                    for phase in ('running', 'completed'):
                        state = monitor.AgentState('ses_1', 'Task', 'project', None, phase, phase.title(), None, 0, 0, 0, datetime.now(timezone.utc))
                        for source in monitor.SOURCES:
                            extra = monitor.activity_message(source, state, 'create')['surfaces']['extraLiveActivity']
                            self.assertEqual(set(extra), {'leftSlot'})
                            self.assertEqual(extra['leftSlot'], monitor.source_logo(source))

    def test_opencode_phase_completion_and_failure(self):
        self.assertEqual(monitor.opencode_phase({'role': 'assistant', 'time': {'completed': 10}, 'finish': 'stop'}, None)[0], 'completed')
        self.assertEqual(monitor.opencode_phase({'role': 'assistant', 'error': {'name': 'error'}}, None)[0], 'failed')
        self.assertEqual(monitor.opencode_phase({'role': 'user'}, None)[0], 'running')

    def test_source_switch_dismisses_and_reenables_without_restart(self):
        state = monitor.AgentState('ses_1', 'Task', 'project', None, 'running', 'Working', None, 0, 0, 0, datetime.now(timezone.utc))
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'settings.json'
            values = {'enableOpenCode': True}
            settings.write_text(json.dumps({'values': values}))
            with patch.dict(os.environ, {
                'DYNAMICLAKE_PLUGIN_SETTINGS_PATH': str(settings),
                'AI_AGENTS_ENABLE_CODEX': '0',
                'AI_AGENTS_ENABLE_CLAUDE': '0',
            }):
                plugin = monitor.AgentsJSONPlugin()
                sent = []
                plugin.client.send = sent.append
                with patch.object(monitor, 'load_latest_state', return_value=state) as load:
                    plugin.refresh_sources()
                    self.assertEqual([message['type'] for message in sent], ['dismiss', 'dismiss', 'create'])
                    self.assertEqual(sent[-1]['activityID'], monitor.OPENCODE.activity_id)
                    self.assertEqual(load.call_count, 1)

                    values['enableOpenCode'] = False
                    settings.write_text(json.dumps({'values': values}))
                    plugin.refresh_sources()
                    self.assertEqual([message['type'] for message in sent[-2:]], ['create', 'dismiss'])
                    self.assertEqual(load.call_count, 1)

                    values['enableOpenCode'] = True
                    settings.write_text(json.dumps({'values': values}))
                    plugin.refresh_sources()
                    self.assertEqual([message['type'] for message in sent[-3:]], ['create', 'dismiss', 'create'])
                    self.assertEqual(load.call_count, 2)

    def test_host_codex_claude_controls_ignore_old_duplicate_values(self):
        values = {'enableCodex': True, 'enableClaude': True, 'enableOpenCode': True}
        with patch.dict(os.environ, {'AI_AGENTS_ENABLE_CODEX': '0', 'AI_AGENTS_ENABLE_CLAUDE': '0'}):
            self.assertEqual(monitor.enabled_sources(values), (monitor.OPENCODE,))
        values['enableCodex'] = False
        values['enableClaude'] = False
        with patch.dict(os.environ, {'AI_AGENTS_ENABLE_CODEX': '1', 'AI_AGENTS_ENABLE_CLAUDE': '1'}):
            self.assertEqual(monitor.enabled_sources(values), monitor.SOURCES)

    def test_restart_dismisses_orphaned_inactive_activity_once(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=5)
        state = monitor.AgentState('ses_1', 'Task', 'project', None, 'running', 'Working', None, 0, 0, 0, old)
        plugin = monitor.AgentsJSONPlugin()
        sent = []
        plugin.client.send = sent.append
        with patch.object(monitor, 'enabled_sources', return_value=(monitor.CODEX,)):
            with patch.object(monitor, 'load_latest_state', return_value=state):
                plugin.refresh_sources()
                plugin.refresh_sources()
        self.assertEqual([(message['type'], message['activityID']) for message in sent], [
            ('dismiss', source.activity_id) for source in monitor.SOURCES
        ])

    def test_codex_metadata_write_does_not_revive_completed_turn(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=5)
        parser = monitor.CodexSessionParser()
        for event, kind in ((old, 'task_started'), (old + timedelta(seconds=2), 'task_complete')):
            parser.consume(json.dumps({'timestamp': event.isoformat(), 'type': 'event_msg',
                                       'payload': {'type': kind, 'turn_id': 'turn_1'}}))
        parser.consume(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(),
                                   'type': 'event_msg', 'payload': {'type': 'thread_settings_applied'}}))
        state = parser.snapshot()
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(state['updated_at'], old + timedelta(seconds=2))

    def test_codex_large_log_does_not_carry_old_turn_into_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = Path(directory) / 'sessions'
            sessions.mkdir()
            log = sessions / 'rollout-large.jsonl'
            old = datetime.now(timezone.utc) - timedelta(minutes=5)
            with log.open('w') as output:
                def write(timestamp, event_type, payload):
                    output.write(json.dumps({'timestamp': timestamp.isoformat(), 'type': event_type,
                                             'payload': payload}) + '\n')

                write(old - timedelta(hours=1), 'session_meta', {'id': 'ses_1', 'cwd': '/tmp/project'})
                write(old - timedelta(hours=1), 'event_msg', {'type': 'task_started', 'turn_id': 'old_turn'})
                filler = json.dumps({'type': 'ignored', 'padding': 'x' * 1000}) + '\n'
                output.write(filler * 110)
                write(old - timedelta(seconds=2), 'event_msg', {'type': 'task_started', 'turn_id': 'new_turn'})
                output.write(filler * 530)
                write(old, 'event_msg', {'type': 'task_complete', 'turn_id': 'new_turn'})

            self.assertGreater(log.stat().st_size, monitor.MAX_HEAD_BYTES + monitor.MAX_TAIL_BYTES)
            with patch.dict(os.environ, {'CODEX_HOME': directory}):
                state = monitor.load_codex_state()
            self.assertEqual((state.session_id, state.phase, state.updated_at), ('ses_1', 'completed', old))
            self.assertFalse(state.is_active)


if __name__ == '__main__':
    unittest.main()
