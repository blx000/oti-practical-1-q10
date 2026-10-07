"""Create private local config and register the three Iceberg warehouses."""
import json
import os
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
ENV = ROOT / '.env'


def create_config():
    if not ENV.exists():
        values = {
            'MINIO_ROOT_USER': 'lakehouse',
            'MINIO_ROOT_PASSWORD': secrets.token_urlsafe(24),
            'POSTGRES_PASSWORD': secrets.token_urlsafe(24),
            'LAKEKEEPER_PG_ENCRYPTION_KEY': secrets.token_urlsafe(32),
            'SUPERSET_SECRET_KEY': secrets.token_urlsafe(48),
            'SUPERSET_ADMIN_PASSWORD': secrets.token_urlsafe(24),
        }
        ENV.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
        ENV.chmod(0o600)
    values = dict(line.strip().split('=', 1) for line in ENV.read_text().splitlines() if '=' in line)
    catalog = LOCAL / 'catalog'
    catalog.mkdir(parents=True, exist_ok=True)
    (catalog / 'tpch.properties').write_text('connector.name=tpch\n')
    for layer in ('bronze', 'silver', 'gold'):
        properties = f'''connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://lakekeeper:8181/catalog
iceberg.rest-catalog.warehouse={layer}
iceberg.rest-catalog.nested-namespace-enabled=true
iceberg.unique-table-location=true
fs.native-s3.enabled=true
s3.endpoint=http://minio:9000
s3.path-style-access=true
s3.region=us-east-1
s3.aws-access-key={values['MINIO_ROOT_USER']}
s3.aws-secret-key={values['MINIO_ROOT_PASSWORD']}
'''
        (catalog / f'{layer}.properties').write_text(properties)
    for p in catalog.iterdir():
        p.chmod(0o600)
    return values


def request(url, data=None):
    payload = None if data is None else json.dumps(data).encode()
    req = Request(url, payload, {'Content-Type': 'application/json'}, method='POST' if payload else 'GET')
    try:
        with urlopen(req, timeout=10) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except HTTPError as exc:
        return exc.code, exc.read().decode()


def register_warehouses(values):
    base = 'http://localhost:8181'
    for _ in range(60):
        try:
            code, _ = request(base + '/health')
            if code == 200:
                break
        except URLError:
            pass
        time.sleep(2)
    else:
        raise RuntimeError('Lakekeeper did not become healthy')
    code, body = request(base + '/management/v1/bootstrap', {'accept-terms-of-use': True})
    print('bootstrap:', code, body)
    for layer in ('bronze', 'silver', 'gold'):
        data = {
            'warehouse-name': layer,
            'project-id': '00000000-0000-0000-0000-000000000000',
            'storage-profile': {
                'type': 's3', 'bucket': layer, 'key-prefix': '',
                'endpoint': 'http://minio:9000', 'region': 'us-east-1',
                'path-style-access': True, 'flavor': 's3-compat', 'sts-enabled': False,
            },
            'storage-credential': {
                'type': 's3', 'credential-type': 'access-key',
                'access-key-id': values['MINIO_ROOT_USER'],
                'secret-access-key': values['MINIO_ROOT_PASSWORD'],
            },
        }
        code, body = request(base + '/management/v1/warehouse', data)
        print(layer, code, body if code not in (201, 409) else '')
        if code not in (201, 409):
            raise RuntimeError(f'Could not register {layer}: {code} {body}')


if __name__ == '__main__':
    values = create_config()
    if '--register' in os.sys.argv:
        register_warehouses(values)
    else:
        print('Private .env and catalog files are ready.')
