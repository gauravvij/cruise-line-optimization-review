import json, urllib.request
from pathlib import Path
cfg=json.loads(Path.home().joinpath('.config/openrouter/config').read_text())
req=urllib.request.Request('https://openrouter.ai/api/v1/key', headers={'Authorization': f"Bearer {cfg['api_key']}"})
with urllib.request.urlopen(req, timeout=60) as r:
    d=json.load(r)
print(d['data']['usage_monthly'])
