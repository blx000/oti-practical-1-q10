"""Load Q10 medallion, run reproducible benchmarks, and save verified results."""
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from trino_client import query

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.local' / 'results.json'
PUBLIC_RESULTS = ROOT / 'results' / 'measurements.json'
TABLES = ('customer', 'orders', 'lineitem', 'nation')


def run(sql, session=None):
    result = query(sql, session)
    print(result['query_id'], result['stats'].get('elapsedTimeMillis'), sql[:90].replace('\n', ' '), flush=True)
    return result


def scalar(sql):
    return run(sql)['rows'][0][0]


def size(catalog, schema, table):
    return scalar(f'SELECT coalesce(sum(file_size_in_bytes), 0) FROM {catalog}.{schema}."{table}$files"')


def count(catalog, schema, table):
    return scalar(f'SELECT count(*) FROM {catalog}.{schema}.{table}')


def load_bronze(schema='lab', format_='PARQUET', codec='GZIP'):
    run(f'CREATE SCHEMA IF NOT EXISTS bronze.{schema}')
    summary = {}
    for table in TABLES:
        run(f'DROP TABLE IF EXISTS bronze.{schema}.{table}')
        r = run(f'''CREATE TABLE bronze.{schema}.{table}
          WITH (format = '{format_}')
          AS SELECT * FROM tpch.sf1.{table}''', f'bronze.compression_codec={codec}')
        summary[table] = {
            'rows': count('bronze', schema, table),
            'bytes': size('bronze', schema, table),
            'write_ms': r['stats'].get('elapsedTimeMillis'),
        }
    return summary


Q10 = '''SELECT c.custkey, c.name,
  sum(l.extendedprice * (1 - l.discount)) AS revenue,
  c.acctbal, n.name AS nation, c.address, c.phone, c.comment
FROM {source}.customer c
JOIN {source}.orders o ON c.custkey = o.custkey
JOIN {source}.lineitem l ON o.orderkey = l.orderkey
JOIN {source}.nation n ON c.nationkey = n.nationkey
WHERE o.orderdate >= DATE '1993-10-01'
  AND o.orderdate < DATE '1994-01-01'
  AND l.returnflag = 'R'
GROUP BY c.custkey, c.name, c.acctbal, n.name, c.address, c.phone, c.comment
ORDER BY revenue DESC, c.custkey
LIMIT 20'''


def medallion():
    for layer in ('silver', 'gold'):
        run(f'CREATE SCHEMA IF NOT EXISTS {layer}.lab')
    run('DROP TABLE IF EXISTS silver.lab.customer_nation')
    run('''CREATE TABLE silver.lab.customer_nation
      WITH (format = 'PARQUET') AS
      SELECT c.custkey, c.name, c.acctbal, c.address, c.phone,
             c.comment, c.nationkey, n.name AS nation
      FROM bronze.lab.customer c
      JOIN bronze.lab.nation n ON c.nationkey = n.nationkey
      WHERE c.custkey IS NOT NULL AND n.nationkey IS NOT NULL''', 'silver.compression_codec=ZSTD')
    run('DROP TABLE IF EXISTS silver.lab.returned_items_q4_1993')
    run('''CREATE TABLE silver.lab.returned_items_q4_1993
      WITH (format = 'PARQUET') AS
      SELECT o.custkey, o.orderkey, o.orderdate, l.linenumber,
             l.extendedprice, l.discount, l.returnflag,
             l.extendedprice * (1 - l.discount) AS line_revenue
      FROM bronze.lab.orders o
      JOIN bronze.lab.lineitem l ON o.orderkey = l.orderkey
      WHERE o.orderdate >= DATE '1993-10-01'
        AND o.orderdate < DATE '1994-01-01'
        AND l.returnflag = 'R'
        AND o.custkey IS NOT NULL AND l.extendedprice >= 0
        AND l.discount BETWEEN 0 AND 1''', 'silver.compression_codec=ZSTD')
    run('DROP TABLE IF EXISTS gold.lab.q10_top20_customers')
    run('''CREATE TABLE gold.lab.q10_top20_customers
      WITH (format = 'PARQUET') AS
      SELECT c.custkey, c.name, sum(l.line_revenue) AS revenue,
             c.acctbal, c.nation, c.address, c.phone, c.comment
      FROM silver.lab.customer_nation c
      JOIN silver.lab.returned_items_q4_1993 l ON c.custkey = l.custkey
      GROUP BY c.custkey, c.name, c.acctbal, c.nation, c.address, c.phone, c.comment
      ORDER BY revenue DESC, c.custkey LIMIT 20''', 'gold.compression_codec=SNAPPY')
    return {f'{layer}.{table}': {'rows': count(layer, 'lab', table), 'bytes': size(layer, 'lab', table)}
            for layer, table in [('silver', 'customer_nation'), ('silver', 'returned_items_q4_1993'),
                                 ('gold', 'q10_top20_customers')]}


def compare():
    source = run(Q10.format(source='tpch.sf1'))['rows']
    bronze = run(Q10.format(source='bronze.lab'))['rows']
    gold = run('SELECT custkey, name, revenue, acctbal, nation, address, phone, comment '
               'FROM gold.lab.q10_top20_customers ORDER BY revenue DESC, custkey')['rows']
    issues = []
    for label, other in [('bronze', bronze), ('gold', gold)]:
        if len(other) != len(source):
            issues.append(f'{label}: row count {len(other)} != {len(source)}')
            continue
        for i, (expected, actual) in enumerate(zip(source, other)):
            for j, (a, b) in enumerate(zip(expected, actual)):
                if j == 2:
                    if not math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=0.0001):
                        issues.append(f'{label} row {i}: revenue {a} != {b}')
                elif a != b:
                    issues.append(f'{label} row {i} column {j}: {a} != {b}')
    checks = {
        'bronze_counts': {t: count('bronze', 'lab', t) for t in TABLES},
        'silver_customer_duplicates': scalar('SELECT count(*) - count(DISTINCT custkey) FROM silver.lab.customer_nation'),
        'silver_line_duplicates': scalar('SELECT count(*) - count(DISTINCT CAST(orderkey AS varchar) || \'-\' || CAST(linenumber AS varchar)) FROM silver.lab.returned_items_q4_1993'),
        'silver_invalid_money': scalar('SELECT count(*) FROM silver.lab.returned_items_q4_1993 WHERE extendedprice < 0 OR discount NOT BETWEEN 0 AND 1'),
        'q10_match_issues': issues,
        'top20': gold,
    }
    if issues or checks['silver_customer_duplicates'] or checks['silver_line_duplicates'] or checks['silver_invalid_money']:
        raise RuntimeError(f'Validation failed: {issues[:3]}')
    return checks


def benchmark():
    results = []
    for format_ in ('PARQUET', 'ORC'):
        for codec in ('GZIP', 'ZSTD'):
            schema = f"bench_{format_.lower()}_{codec.lower()}"
            tables = load_bronze(schema, format_, codec)
            sql = Q10.format(source=f'bronze.{schema}')
            warmup = run(sql)
            reference = json.loads(OUT.read_text())['validation']['top20']
            matches = len(warmup['rows']) == len(reference) and all(
                actual[0] == expected[0] and
                math.isclose(float(actual[2]), float(expected[2]), rel_tol=1e-12, abs_tol=0.0001)
                for actual, expected in zip(warmup['rows'], reference))
            if not matches:
                raise RuntimeError(f'{schema}: Q10 differs from validated Gold')
            samples = [run(sql)['stats'].get('elapsedTimeMillis') for _ in range(5)]
            results.append({'format': format_, 'codec': codec, 'schema': schema,
                            'tables': tables, 'total_bytes': sum(v['bytes'] for v in tables.values()),
                            'total_write_ms': sum(v['write_ms'] for v in tables.values()),
                            'warmup_ms': warmup['stats'].get('elapsedTimeMillis'),
                            'samples_ms': samples, 'median_ms': statistics.median(samples),
                            'q10_matches_reference': matches,
                            'min_ms': min(samples), 'max_ms': max(samples)})
            save({'benchmark': results})
    return results


def evolution():
    run('DROP TABLE IF EXISTS silver.lab.schema_evolution_demo')
    run('''CREATE TABLE silver.lab.schema_evolution_demo
      WITH (format = 'PARQUET') AS
      SELECT custkey, name FROM silver.lab.customer_nation ORDER BY custkey LIMIT 5''', 'silver.compression_codec=ZSTD')
    before = scalar('SELECT snapshot_id FROM silver.lab."schema_evolution_demo$snapshots" ORDER BY committed_at DESC LIMIT 1')
    old_count = scalar(f'SELECT count(*) FROM silver.lab.schema_evolution_demo FOR VERSION AS OF {before}')
    run('ALTER TABLE silver.lab.schema_evolution_demo ADD COLUMN source_system varchar')
    run('ALTER TABLE silver.lab.schema_evolution_demo RENAME COLUMN source_system TO origin_system')
    run("INSERT INTO silver.lab.schema_evolution_demo (custkey, name, origin_system) VALUES (-1, 'demo', 'manual')")
    new_count = count('silver', 'lab', 'schema_evolution_demo')
    return {'old_snapshot_id': before, 'old_count': old_count, 'new_count': new_count,
            'new_column': 'origin_system',
            'old_rows_null_in_new_column': scalar('SELECT count(*) FROM silver.lab.schema_evolution_demo WHERE origin_system IS NULL')}


def save(update):
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data.update(update)
    data['measured_at_utc'] = datetime.now(timezone.utc).isoformat()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    OUT.write_text(content)
    PUBLIC_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_RESULTS.write_text(content)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if mode in ('all', 'load'):
        save({'bronze': load_bronze(), 'medallion': medallion(), 'validation': compare()})
    if mode in ('all', 'benchmark'):
        save({'benchmark': benchmark()})
    if mode in ('all', 'evolution'):
        save({'evolution': evolution()})
