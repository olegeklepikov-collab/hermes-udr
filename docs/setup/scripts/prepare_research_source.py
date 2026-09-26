"""Download/verify the published Research ZIP and prepare a local install source.
Does not install or enable a plugin and never loads private signing material.
"""
import argparse,hashlib,json,subprocess,urllib.request,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--minisign',default='minisign');p.add_argument('--component',choices=['research','foundation'],default='research');a=p.parse_args()
root=a.directory.resolve();root.mkdir(parents=True,exist_ok=True)
lock=json.loads((Path(__file__).resolve().parents[1]/'reference/native-tools.lock.json').read_text(encoding='utf-8'))
record=lock['release_artifacts'][a.component]
base='https://github.com/olegeklepikov-collab/hermes-udr/releases/download/'+lock['release']+'/'
name=record['name']
expected={'release-signing.pub':lock['signing_public_key_sha256'],name:record['sha256']}
for n in [name,name+'.minisig','release-signing.pub']:
 path=root/n
 if not path.exists():
  with urllib.request.urlopen(base+n,timeout=90) as r,path.open('xb') as out:
   while chunk:=r.read(1024*1024):out.write(chunk)
 if n in expected and hashlib.sha256(path.read_bytes()).hexdigest()!=expected[n]:raise SystemExit('Hash mismatch: '+n)
subprocess.run([a.minisign,'-Vm',str(root/name),'-p',str(root/'release-signing.pub')],check=True)
source=root/(a.component+'-source')
if source.exists():raise SystemExit('Verified archives retained; source already exists. Do not overwrite it.')
source.mkdir()
with zipfile.ZipFile(root/name) as z:
 for n in z.namelist():
  relative=Path(n)
  if relative.is_absolute() or '..' in relative.parts or '\\' in n:raise SystemExit('Invalid ZIP member')
  target=source/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(n))
 manifest=json.loads((source/'bundle-manifest.json').read_text(encoding="utf-8"))
 for row in manifest['files']:
  if hashlib.sha256((source/row['path']).read_bytes()).hexdigest()!=row['sha256']:raise SystemExit('Member hash mismatch')
def run(args):return subprocess.run(['git','-C',str(source),*args],check=True,capture_output=True,text=True).stdout.strip()
run(['init','--quiet']);run(['config','core.autocrlf','false']);run(['config','user.name','Hermes UDR local installer']);run(['config','user.email','local@localhost.invalid'])
run(['add','--',*[x['path'] for x in manifest['files']],'bundle-manifest.json']);run(['commit','--quiet','-m','Verified '+a.component+' release bytes'])
ref=run(['rev-parse','HEAD'])
print(json.dumps({'source_uri':source.as_uri(),'local_install_commit':ref,'install_argv':['hermes','plugins','install',source.as_uri(),'--ref',ref,'--no-enable'],'signature_verified':True},ensure_ascii=False,indent=2))
