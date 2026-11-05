FROM postgres:16-bookworm AS pgtools
FROM python:3.12-slim-bookworm
WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 libzstd1 liblz4-1 && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 secretai && useradd --uid 10001 --gid secretai --create-home secretai
COPY --from=pgtools /usr/lib/postgresql/16/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=pgtools /usr/lib/postgresql/16/bin/pg_restore /usr/local/bin/pg_restore
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
COPY scripts ./scripts
ENV SECRET_AI_DB=/srv/data/secretai.db
RUN mkdir -p /srv/data && chown -R secretai:secretai /srv/data
USER secretai
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "172.30.0.10"]
