"""Read controller choices without exposing credentials or executing inference."""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,119}', value) is not None


def codex_models(cache):
    if not cache.is_file():
        return {'models': [], 'message': 'No Codex catalog yet. Open Codex to refresh it, or enter a custom model ID.'}
    if cache.stat().st_size > 16 * 1024 * 1024: raise ValueError('oversized catalog')
    data = json.loads(cache.read_text())
    models = [{'id': m['slug'], 'name': m.get('display_name') or m['slug']}
              for m in data.get('models', []) if m.get('visibility') == 'list' and valid_id(m.get('slug'))]
    return {'models': models, 'source': 'codex-cache', 'updated_at': data.get('fetched_at'),
            'message': 'From your local Codex catalog. Model access is checked when the agent starts.'}


def api_models(key):
    if not key: return {'models': [], 'message': 'Configure OPENAI_API_KEY on the server to load API models.'}
    request = urllib.request.Request('https://api.openai.com/v1/models', headers={'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024: raise ValueError('oversized catalog')
    data = json.loads(payload)
    # The catalog does not specify Responses / structured-output compatibility.
    # Exclude obvious non-text families; keep an explicit compatibility note.
    excluded = ('image', 'audio', 'realtime', 'transcribe', 'tts', 'embedding', 'moderation', 'whisper', 'sora')
    models = [{'id': m['id'], 'name': m['id']} for m in data.get('data', [])
              if valid_id(m.get('id')) and not any(term in m['id'].lower() for term in excluded)]
    models.sort(key=lambda m: m['id'])
    return {'models': models, 'source': 'openai-api',
            'message': 'Account model list. Choose a model supporting Responses and structured outputs.'}


def catalog(backend):
    try:
        if backend == 'codex':
            return codex_models(Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))) / 'models_cache.json')
        if backend == 'openai': return api_models(os.environ.get('OPENAI_API_KEY'))
        raise ValueError('unsupported backend')
    except Exception:
        # Never send provider error bodies or credentials to the browser.
        return {'models': [], 'message': 'Model list unavailable. Check the backend configuration or enter a custom model ID.'}

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--backend', choices=['codex','openai'], required=True)
    print(json.dumps(catalog(p.parse_args().backend)))
