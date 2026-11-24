import json, urllib.request
from pathlib import Path
cfg=json.loads(Path.home().joinpath('.config/openrouter/config').read_text())
key=cfg['api_key']
print('key ends', key[-3:])
req=urllib.request.Request('https://openrouter.ai/api/v1/key', headers={'Authorization': f'Bearer {key}'})
with urllib.request.urlopen(req, timeout=60) as r:
    d=json.load(r)
print(json.dumps(d, indent=1)[:2000])
