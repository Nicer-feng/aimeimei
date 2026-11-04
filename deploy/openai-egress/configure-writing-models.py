#!/usr/bin/env python3
"""Explicit one-time model setup through the local authenticated admin API."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

FX = Decimal('6.7180')
ENDPOINT = 'https://api.openai.com/v1'
MODELS = [('GPT-6.1 Sol', 'gpt-6.1-sol', Decimal('2'), Decimal('10')),
          ('GPT-6.1 Terra', 'gpt-6.1-terra', Decimal('1'), Decimal('5'))]


def specifications():
    return [{"name": name, "model": code, "provider": "OpenAI", "base_url": ENDPOINT,
        "enabled": True, "supports_vision": True, "supports_reasoning_control": True,
        "supports_native_web_search": False, "cost_enabled": True,
        "input_price_per_million": float(input_price * FX), "output_price_per_million": float(output_price * FX),
        "cost_note": "2026-11-04 OpenAI Standard 常规上下文价：输入 $%s、输出 $%s / 百万 Token；按中行折算价 1 USD=6.7180 CNY 固定估算。未计缓存优惠、缓存写入、超272K输入及特殊服务档位差异，不代表实际账单。" % (input_price, output_price)}
        for name, code, input_price, output_price in MODELS]


def apply(data_dir, backup_dir, api_base='http://127.0.0.1:8000'):
    if urlparse(api_base).hostname != '127.0.0.1' or urlparse(api_base).scheme != 'http':
        raise RuntimeError('local admin API required')
    data_dir, backup_dir = Path(data_dir), Path(backup_dir)
    if not backup_dir.is_dir() or backup_dir.stat().st_mode & 0o077:
        raise RuntimeError('existing private backup directory required')
    backup_dir = backup_dir / ('model-config-' + str(time.time_ns()))
    backup_dir.mkdir(mode=0o700)
    key = (data_dir / 'admin.key').read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, body=None, method='GET'):
        req = urllib.request.Request(api_base + path,
            headers={'X-Admin-Key': key, 'Content-Type': 'application/json'},
            data=json.dumps(body).encode() if body is not None else None, method=method)
        try:
            with opener.open(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            status = error.code; error.close()
            raise RuntimeError('admin API returned HTTP ' + str(status)) from None
    before = request('/api/admin/models')['models']
    # Store only public metadata; the consistent SQLite backup is separately private.
    (backup_dir / 'models-before.json').write_text(json.dumps(before, ensure_ascii=False))
    (backup_dir / 'models-before.json').chmod(0o600)
    with sqlite3.connect('file:' + str(data_dir / 'ai-platform.db') + '?mode=ro', uri=True) as source:
        with sqlite3.connect(backup_dir / 'models-before.sqlite') as destination:
            source.backup(destination)
    (backup_dir / 'models-before.sqlite').chmod(0o600)
    target_codes = {spec['model'] for spec in specifications()}
    untouched = {r['id']: r for r in before if not (r['base_url'].rstrip('/') == ENDPOINT and r['model'] in target_codes)}
    configured = []
    for spec in specifications():
        existing = [r for r in before if r['base_url'].rstrip('/') == ENDPOINT and r['model'] == spec['model']]
        if len(existing) > 1:
            raise RuntimeError('duplicate official model; no automatic merge')
        if existing:
            row = existing[0]
            update = {k: v for k, v in spec.items() if k not in ('name', 'provider', 'enabled')}
            result = request('/api/admin/models/' + row['id'], update, method='PUT')['model']
        else:
            result = request('/api/admin/models', {**spec, 'api_key': '', 'system_prompt': ''}, method='POST')['model']
            assert not result['has_api_key']
        for field in ('input_price_per_million', 'output_price_per_million', 'supports_reasoning_control', 'supports_vision'):
            assert result[field] == spec[field], field
        assert result['reasoning_mode_options']['fast']['effort'] == ('low' if spec['model'].endswith('sol') else 'none')
        fields = ('id', 'name', 'model', 'has_api_key', 'supports_vision', 'supports_reasoning_control',
                  'reasoning_mode_options', 'input_price_per_million', 'output_price_per_million', 'cost_enabled')
        configured.append({field: result[field] for field in fields})
    after = request('/api/admin/models')['models']
    lookup = {row['id']: row for row in after}
    assert all(lookup.get(id_) == row for id_, row in untouched.items()), 'other model configuration changed'
    receipt = {'configured_at': int(time.time()), 'backup': str(backup_dir), 'rate': str(FX), 'rate_source': 'https://www.boc.cn/sourcedb/whpj/',
               'configured': configured, 'other_models_unchanged': len(untouched), 'model_requests': 0}
    (backup_dir / 'models-after.json').write_text(json.dumps(receipt, ensure_ascii=False))
    (backup_dir / 'models-after.json').chmod(0o600)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--data-dir', default='/opt/ai-platform')
    parser.add_argument('--backup-dir')
    args = parser.parse_args()
    if args.apply:
        if not args.backup_dir:
            parser.error('--apply requires --backup-dir')
        apply(args.data_dir, args.backup_dir)
    else:
        print(json.dumps({'dry_run': True, 'models': specifications()}, ensure_ascii=False))
