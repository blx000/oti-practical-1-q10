FROM apache/superset:6.0.0
USER root
RUN uv pip install --python /app/.venv/bin/python sqlalchemy-trino
USER superset
CMD ["/bin/sh", "-c", "superset db upgrade && (superset fab create-admin --username admin --firstname Artemiy --lastname Levchenkov --email admin@localhost --password \"$SUPERSET_ADMIN_PASSWORD\" || true) && superset init && gunicorn -w 1 -k gthread --threads 4 --timeout 120 -b 0.0.0.0:8088 'superset.app:create_app()'"]
