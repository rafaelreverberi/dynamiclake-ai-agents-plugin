#!/usr/bin/env python3
"""Run the extracted monitor against a framed socket host with synthetic sessions."""
import base64
import json
import os
from pathlib import Path
import platform
import shlex
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone


def extract(archive, root):
    # Use the system extractor so the exact executable modes in the ZIP are tested.
    subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(root)], check=True)
    package, = root.glob('*.dynamiclakeplugin')
    manifest = json.loads((package/'plugin.json').read_text())
    return package, package/manifest['executable']


def check_hooks(command, env, executable):
    claude = Path(env['CLAUDE_HOME'])/'settings.json'
    codex = Path(env['CODEX_HOME'])/'hooks.json'
    claude.parent.mkdir(parents=True)
    unrelated = {'hooks':[{'type':'command','command':'keep-existing'}]}
    legacy = {'type':'command','command':
              '/absent/python3 /absent/agent_hook.py claude PermissionRequest dynamiclake-ai-agents-hook'}
    claude.write_text(json.dumps({'theme':'keep','hooks':{'PermissionRequest':[unrelated,{'hooks':[legacy]}]},
        'statusLine':{**legacy,'command':legacy['command'].replace('PermissionRequest','Usage')}}))
    codex_legacy = {**legacy,'command':legacy['command'].replace(' claude ',' codex ')}
    codex.write_text(json.dumps({'hooks':{'PermissionRequest':[unrelated,{'hooks':[codex_legacy]}]}}))

    def setup(action, provider):
        subprocess.run([*command,'--setup',action,provider],env=env,check=True,capture_output=True,timeout=8)

    setup('install','claude')
    setup('install-usage','claude')
    setup('install','codex')
    document=json.loads(claude.read_text())
    codex_document=json.loads(codex.read_text())
    assert document['theme']=='keep' and document['hooks']['PermissionRequest'][0]==unrelated
    assert codex_document['hooks']['PermissionRequest'][0]==unrelated
    assert len(document['hooks']['PermissionRequest'])==len(codex_document['hooks']['PermissionRequest'])==2

    def verify(entry, provider, event, payload, response, expected):
        argv=shlex.split(entry['command'])
        assert argv==[str(executable.resolve()),'--hook',provider,event,'dynamiclake-ai-agents-hook'],argv
        # Invoke the saved command exactly like the provider. For the Intel
        # smoke run, force the binary slice as well as checking the saved path.
        invoke=command[:-1]+argv
        sockpath=Path(env['AI_AGENTS_BRIDGE_DIR'])/'hooks.sock'
        sockpath.parent.mkdir(mode=0o700,exist_ok=True)
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(sockpath));server.listen();server.settimeout(5)
            with subprocess.Popen(invoke,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as hook:
                try:
                    hook.stdin.write(json.dumps(payload).encode());hook.stdin.close();hook.stdin=None
                    peer,_=server.accept()
                    with peer:
                        peer.settimeout(4)
                        with peer.makefile('rb') as stream: message=json.loads(stream.readline())
                        assert message['provider']==provider and message['event']==event
                        assert message['data']['session_id']==payload['session_id']
                        assert 'prompt' not in message['data']
                        peer.sendall(json.dumps(response).encode()+b'\n')
                    output,errors=hook.communicate(timeout=4)
                    assert hook.returncode==0,(output,errors)
                    assert output.decode().strip()==expected,(output,expected)
                finally:
                    if hook.poll() is None:hook.kill()
        sockpath.unlink()

    payload={'session_id':'fixture','tool_name':'Bash','prompt':'do not forward'}
    for provider, config, decision in (('claude',document,'allow'),('codex',codex_document,'deny')):
        result={'hookSpecificOutput':{'hookEventName':'PermissionRequest','decision':{'behavior':decision}}}
        verify(config['hooks']['PermissionRequest'][1]['hooks'][0],provider,'PermissionRequest',
               payload,{'decision':decision},json.dumps(result))
    verify(document['hooks']['PreToolUse'][0]['hooks'][0],'claude','PreToolUse',payload,{},'{}')
    verify(document['statusLine'],'claude','Usage',{'session_id':'fixture','rate_limits':{
        'five_hour':{'used_percentage':20,'resets_at':time.time()+3600}}},{},'Claude · 80% 5-hour left')
    # With the monitor offline the hook must return to the provider's own prompt.
    fallback=subprocess.check_output([*command,'--hook','codex','PermissionRequest'],input=json.dumps(payload),
                                     env=env,text=True,timeout=5)
    assert json.loads(fallback)=={}
    setup('uninstall','codex')
    setup('uninstall','claude')
    assert json.loads(codex.read_text())=={'hooks':{'PermissionRequest':[unrelated]}}
    assert json.loads(claude.read_text())=={'theme':'keep','hooks':{'PermissionRequest':[unrelated]}}
    for config in (claude,codex):
        backups=list(config.parent.glob('*.dynamiclake-backup-*'))
        assert backups and all((p.stat().st_mode & 0o777)==0o600 for p in backups)


def check_sqlite(command, env):
    database=Path(env['OPENCODE_DB'])
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE session_v2(id TEXT PRIMARY KEY,directory TEXT,title TEXT,time_updated INTEGER,
                time_archived INTEGER,time_busy INTEGER,time_idle INTEGER,idle_outcome TEXT);
            CREATE TABLE session_message(id TEXT PRIMARY KEY,session_id TEXT,type TEXT,seq INTEGER,
                time_created INTEGER,time_updated INTEGER,data TEXT);
            CREATE TABLE session_part(message_id TEXT,session_id TEXT,ordinal INTEGER,type TEXT,call_id TEXT,
                time_created INTEGER,time_updated INTEGER,data TEXT);
        """)
        now=int(time.time()*1000)
        db.execute('INSERT INTO session_v2 VALUES(?,?,?,?,NULL,?,NULL,NULL)',
                   ('fixture','/tmp/project','Example',now,now))
        db.execute('INSERT INTO session_message VALUES(?,?,?,?,?,?,?)',
                   ('message','fixture','assistant',1,now,now,json.dumps({'time':{'created':now},
                    'content':[{'type':'tool','id':'fixture-call','name':'read',
                                'state':{'status':'running','input':{'file_path':'/tmp/fixture.swift'}}}]})))
    check=json.loads(subprocess.check_output([*command,'--check'],env=env,timeout=5))
    assert check['sessions']['opencode']==1 and check['active']==1,check
    database.unlink()


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


def smoke(archive, architecture):
    # macOS Unix socket paths are limited to roughly 104 bytes.
    with tempfile.TemporaryDirectory(prefix='aia-',dir='/tmp') as folder:
        root=Path(folder)
        install=root/"Installed Plugins – O'Neil";install.mkdir()
        package,executable=extract(archive,install)
        command=['/usr/bin/arch','-'+architecture,str(executable)]
        settings=root/'settings.json'
        env={'HOME':folder,'PATH':'/nonexistent','TMPDIR':folder,'LC_ALL':'C',
             'PYTHONHOME':'/nonexistent','PYTHONPATH':'/nonexistent','DYLD_LIBRARY_PATH':'/nonexistent',
             'CODEX_HOME':str(root/'codex'),'CLAUDE_HOME':str(root/'claude'),
             'XDG_DATA_HOME':str(root/'data'),'OPENCODE_DB':str(root/'OpenCode émoi #?.db'),
             'AI_AGENTS_BRIDGE_DIR':str(root/'ipc'),'DYNAMICLAKE_PLUGIN_SETTINGS_PATH':str(settings),
             'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout,imageAssets,presentSneakPeek'}
        before=set(package.rglob('*'))
        # First execution after extraction can take several seconds while macOS
        # checks the binary and Rosetta translates its Intel slice.
        assert json.loads(subprocess.check_output([*command,'--check'],env=env,timeout=30))['active']==0
        check_sqlite(command,env)
        sessions=root/'codex/sessions';sessions.mkdir(parents=True)
        check_hooks(command,env,executable)
        now=datetime.now(timezone.utc).isoformat()
        for sid in ('one','two'):
            records=[{'timestamp':now,'type':'session_meta','payload':{'id':sid,'cwd':'/tmp/fixture-project'}},
                     {'timestamp':now,'type':'event_msg','payload':{'type':'task_started','turn_id':sid}}]
            (sessions/(sid+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in records))
        settings.write_text(json.dumps({'values':{
            'hideProjectNames':True,'enableUsageTracking':False,'enableHooks':False
        }}))
        sockpath=root/'host.sock'
        with socket.socket(socket.AF_UNIX) as host:
            host.bind(str(sockpath));host.listen();host.settimeout(8)
            env['DYNAMICLAKE_JSON_SOCKET']=str(sockpath)
            process=subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
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
                    assert any(m['type']=='asset' and
                               base64.b64decode(m['asset']['base64Data'])==(package/'logos/codex.png').read_bytes()
                               for m in seen),'Packaged Codex logo was not loaded'
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
                    action['actionID']='tab:setup'
                    data=json.dumps(action).encode()
                    peer.sendall(struct.pack('>I',len(data))+data)
                    for _ in range(12):
                        setup=receive()
                        if setup['type']=='lake':
                            break
                    else:
                        raise AssertionError('Setup callback did not change lake')
                    scroll=next(item for item in setup['lake']['content'] if item['type']=='scroll')
                    titles=[item['title'] for card in scroll['children'] if card['type']=='vstack'
                            for item in card['children'][0]['children'] if item['type']=='button']
                    assert titles==['Setup Claude','Setup Codex','Setup OpenCode']
                    assert len(scroll['children'])==len(titles)
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
                    assert set(package.rglob('*'))==before,'Installed package was mutated'
            finally:
                if process.poll() is None:
                    process.kill();process.communicate()
        print(f'{architecture}: packaged diagnostics, SQLite, migrated hooks and quota IPC, logo, virtual host, reconnect and shutdown passed')


if __name__=='__main__':
    smoke(Path(sys.argv[1]).resolve(), 'x86_64')
    if platform.machine()=='arm64':
        smoke(Path(sys.argv[1]).resolve(), 'arm64')
