"""Render native autostart files for the current OS; never registers or starts them."""
import argparse,json,os,plistlib,shlex,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('spec',type=Path);p.add_argument('out',type=Path);p.add_argument('--platform',choices=['linux','macos','windows'],required=True);a=p.parse_args()
current = {'linux': 'linux', 'darwin': 'macos', 'win32': 'windows'}.get(sys.platform)
if a.platform != current:raise SystemExit('Render services on the target operating system')
spec=a.spec.resolve(strict=True);v=json.loads(spec.read_text(encoding="utf-8-sig"));name=v['name']
if not name.replace('-','').isalnum():raise SystemExit('Use a simple unique service name')
argv=[sys.executable,str(Path(__file__).with_name('service_exec.py').resolve()),str(spec)]
a.out.mkdir(parents=True,exist_ok=True)
if a.platform=='linux':
 def quote(s):return '"'+s.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
 content='[Unit]\nDescription=Hermes UDR '+name+'\nAfter=network-online.target\n\n[Service]\nType=simple\nExecStart='+ ' '.join(map(quote,argv))+'\nRestart=on-failure\nRestartSec=5\nTimeoutStopSec=60\nUMask=0077\n\n[Install]\nWantedBy=default.target\n'
 path=a.out/(name+'.service');path.write_text(content,encoding='utf-8')
elif a.platform=='macos':
 path=a.out/('org.hermesudr.'+name+'.plist')
 log=a.out/(name+'.log')
 path.write_bytes(plistlib.dumps({'Label':'org.hermesudr.'+name,'ProgramArguments':argv,'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':5,'StandardOutPath':str(log.resolve()),'StandardErrorPath':str(log.resolve()),'WorkingDirectory':v['cwd']}))
else:
 def ps(s):return "'"+s.replace("'","''")+"'"
 path=a.out/(name+'-register.ps1')
 arguments=subprocess.list2cmdline(argv[1:])
 path.write_text('$action = New-ScheduledTaskAction -Execute '+ps(argv[0])+' -Argument '+ps(arguments)+'\n$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME\n$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)\nRegister-ScheduledTask -TaskName '+ps('HermesUDR-'+name)+' -Action $action -Trigger $trigger -Settings $settings -Description '+ps('Native Hermes UDR '+name)+'\n',encoding='utf-8-sig')
print(str(path.resolve()))
