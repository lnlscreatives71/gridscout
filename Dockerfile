# gridscout web, for the Hostinger VPS behind Traefik.
#
#   docker build -t gridscout .
#   docker run -d -p 8000:8000 -v gridscout-data:/data \
#     -e DFS_LOGIN=... -e DFS_PASSWORD=... -e ANTHROPIC_API_KEY=... \
#     -e GRIDSCOUT_WEB_PASSWORD=... gridscout
#
# /data holds the SQLite store and every heatmap/PDF, so the volume is the
# whole state. Back that up and the container is disposable.
FROM python:3.12-slim

# WeasyPrint's native text/render stack. The fonts matter: the report falls
# back to whatever the system offers, and slim images offer nothing.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gridscout ./gridscout

ENV GRIDSCOUT_DB=/data/gridscout.db \
    GRIDSCOUT_OUT=/data/output

EXPOSE 8000
CMD ["uvicorn", "gridscout.webapp:app", "--host", "0.0.0.0", "--port", "8000"]
