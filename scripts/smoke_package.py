#!/usr/bin/env python3
"""Run the extracted monitor against a framed socket host with synthetic sessions."""
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone


def validate_lake(message):
    """Check layout limits that cause DynamicLake to reject the entire view."""
    def validate(component, depth=1):
        assert depth<=4,'Lake component is nested too deeply'
        if component.get('type') in ('image','button') and 'size' in component:
            assert 12<=component['size']<=80,'Lake image/button size is outside 12–80 points'
        for child in component.get('children',[]):
            validate(child,depth+1)

    lake=message['lake']
    for layout in (lake,lake.get('glance',{})):
        for key in ('content','bottom'):
            for component in layout.get(key,[]):
                validate(component)


def main(archive):
    # macOS Unix socket paths are limited to roughly 104 bytes.
    with tempfile.TemporaryDirectory(prefix='aia-',dir='/tmp') as folder:
        root=Path(folder)
        with zipfile.ZipFile(archive) as z:z.extractall(root)
        package=root/'AIAgents.dynamiclakeplugin'
        sessions=root/'codex/sessions';sessions.mkdir(parents=True)
        now=datetime.now(timezone.utc).isoformat()
        for sid in ('one','two'):
            records=[{'timestamp':now,'type':'session_meta','payload':{'id':sid,'cwd':'/tmp/fixture-project'}},
                     {'timestamp':now,'type':'event_msg','payload':{'type':'task_started','turn_id':sid}}]
            (sessions/(sid+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in records))
        settings=root/'settings.json'
        settings.write_text(json.dumps({'values':{
            'hideProjectNames':True,'enableUsageTracking':False,'enableHooks':False
        }}))
        sockpath=root/'host.sock'
        with socket.socket(socket.AF_UNIX) as host:
            host.bind(str(sockpath));host.listen();host.settimeout(8)
            env=os.environ.copy();env.update({'HOME':folder,'CODEX_HOME':str(root/'codex'),'CLAUDE_HOME':str(root/'claude'),
                'XDG_DATA_HOME':str(root/'data'),'OPENCODE_DB':str(root/'absent.db'),
                'DYNAMICLAKE_JSON_SOCKET':str(sockpath),'DYNAMICLAKE_PLUGIN_SETTINGS_PATH':str(settings),
                'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout,imageAssets,presentSneakPeek','PYTHONDONTWRITEBYTECODE':'1'})
            process=subprocess.Popen([sys.executable,str(package/'ai-agents-monitor.py')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                peer,_=host.accept()
                with peer:
                    peer.settimeout(8);stream=peer.makefile('rb')
                    def receive():
                        size=stream.read(4)
                        if len(size)!=4:raise AssertionError('Plugin disconnected')
                        count=struct.unpack('>I',size)[0]
                        assert 0<count<=256000
                        message=json.loads(stream.read(count))
                        if message['type']=='lake':
                            validate_lake(message)
                        return message
                    creates=[];seen=[]
                    for _ in range(12):
                        m=receive();seen.append(m)
                        if m['type']=='create':creates.append(m)
                        if m['type']=='lake':break
                    assert len(creates)==1,'Collapsed view must select exactly one active agent'
                    assert '2 sessions' in json.dumps(seen),'Other concurrent session missing'
                    assert 'fixture-project' not in json.dumps(seen), 'Privacy leak'
                    action={'schemaVersion':1,'type':'action','activityID':'lake','surface':'lake','actionID':'tab:usage'}
                    clicked=time.monotonic()
                    data=json.dumps(action).encode();peer.sendall(struct.pack('>I',len(data))+data)
                    found=False
                    for _ in range(8):
                        m=receive()
                        if m['type']=='lake' and m.get('lake',{}).get('content',[{}])[0].get('children',[{},{}])[1].get('text')=='Usage':
                            found=True;break
                    assert found,'Usage callback did not change lake'
                    assert time.monotonic()-clicked<.8,'View switch waited for provider polling'
                    stream.close()
                    peer.close()
                    reconnected,_=host.accept()
                    with reconnected:
                        reconnected.settimeout(8)
                        reconnect_stream=reconnected.makefile('rb')
                        restored=[]
                        for _ in range(12):
                            size=reconnect_stream.read(4)
                            assert len(size)==4,'Reconnect frame missing'
                            m=json.loads(reconnect_stream.read(struct.unpack('>I',size)[0]))
                            if m['type']=='create':restored.append(m['activityID'])
                            if m['type']=='lake':break
                        assert set(restored)=={m['activityID'] for m in creates},'Reconnect did not restore stable sessions'
                        process.send_signal(signal.SIGTERM)
                        process.communicate(timeout=5)
                        reconnect_stream.close()
                    assert process.returncode==0,'Packaged monitor failed shutdown'
                    assert not list(package.rglob('*.pyc')),'Installed package was mutated'
            finally:
                if process.poll() is None:
                    process.kill();process.communicate()
        print('Packaged runtime smoke passed: concurrent tracking / one compact activity, Usage callback, privacy, reconnect, clean shutdown')


if __name__=='__main__':main(sys.argv[1])
