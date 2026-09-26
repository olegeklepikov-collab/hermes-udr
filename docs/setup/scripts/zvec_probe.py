"""Native Zvec 0.7.0 probe in a new directory. No model/API calls."""
import argparse,json
from pathlib import Path
import zvec
p=argparse.ArgumentParser();p.add_argument('path',type=Path);a=p.parse_args()
if a.path.exists():raise SystemExit('Use a new, absent probe directory')
if zvec.__version__ != '0.7.0':
 raise SystemExit(f'Expected zvec 0.7.0, got {zvec.__version__}')
schema=zvec.CollectionSchema(name='native_probe',fields=[zvec.FieldSchema('text',zvec.DataType.STRING,index_param=zvec.FtsIndexParam(tokenizer_name='standard',filters=['lowercase']))],vectors=[zvec.VectorSchema('embedding',zvec.DataType.VECTOR_FP32,dimension=3)])
c=zvec.create_and_open(str(a.path),schema)
try:
 c.insert(zvec.Doc(id='one',fields={'text':'SQLite native storage'},vectors={'embedding':[1.0,0.0,0.0]}))
 c.flush()
 vector_hits=c.query(zvec.Query('embedding',vector=[1.0,0.0,0.0]),topk=1)
 if not vector_hits or vector_hits[0].id!='one':
  raise RuntimeError('Vector query did not return the probe document')
 fts_hits=c.query(zvec.Query('text',fts=zvec.Fts(match_string='SQLite')),topk=1)
 if not fts_hits or fts_hits[0].id!='one':
  raise RuntimeError('FTS query did not return the probe document')
finally:c.close()
c=zvec.open(str(a.path),zvec.CollectionOption(read_only=True))
try:
 reopened_hits=c.query(zvec.Query('text',fts=zvec.Fts(match_string='SQLite')),topk=1)
 if not reopened_hits or reopened_hits[0].id!='one':
  raise RuntimeError('Read-only reopen did not return the probe document')
finally:c.close()
print(json.dumps({'status':'passed','version':zvec.__version__,'vector_query':True,'fts_query':True,'reopen_read_only':True,'semantic_quality_claimed':False}))
