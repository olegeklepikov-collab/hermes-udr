"""Download one exact public archive from the included lock, checking its digest."""
import argparse,hashlib,json,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('directory',type=Path);a=p.parse_args()
lock=json.loads((Path(__file__).resolve().parents[1]/'reference/native-tools.lock.json').read_text(encoding="utf-8"))
record=lock['assets'][a.name]
if '/' in a.name or '\\' in a.name:raise SystemExit('Archive name only')
a.directory.mkdir(parents=True,exist_ok=True);target=a.directory/a.name
if target.exists():
 if hashlib.sha256(target.read_bytes()).hexdigest()!=record['sha256']:raise SystemExit('Existing archive does not match; not overwritten')
else:
 temp=target.with_suffix(target.suffix+'.part')
 with urllib.request.urlopen(record['url'],timeout=90) as response, temp.open('xb') as out:
  while chunk:=response.read(1024*1024):out.write(chunk)
 if hashlib.sha256(temp.read_bytes()).hexdigest()!=record['sha256']:raise SystemExit('Hash mismatch; partial file retained, not installed')
 temp.rename(target)
print(str(target.resolve()))
