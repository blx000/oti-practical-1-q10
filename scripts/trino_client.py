"""Minimal Trino HTTP client using only the Python standard library."""
import json
from urllib.request import Request, urlopen


def query(sql, session=None):
    headers = {'X-Trino-User': 'lab1', 'Content-Type': 'text/plain'}
    if session:
        headers['X-Trino-Session'] = session
    req = Request('http://localhost:8080/v1/statement', sql.encode(), headers)
    with urlopen(req, timeout=120) as response:
        page = json.load(response)
    rows = []
    columns = []
    while True:
        if 'error' in page:
            error = page['error']
            raise RuntimeError(f"{error.get('message')}\nSQL: {sql}")
        if 'columns' in page:
            columns = [c['name'] for c in page['columns']]
        rows.extend(page.get('data', []))
        if 'nextUri' not in page:
            return {'columns': columns, 'rows': rows, 'stats': page.get('stats', {}),
                    'query_id': page.get('id')}
        with urlopen(page['nextUri'], timeout=120) as response:
            page = json.load(response)
