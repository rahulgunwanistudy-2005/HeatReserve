FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEATRESERVE_MODE=judge \
    HEATRESERVE_DATABASE_PATH=/data/heatreserve.db

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY web ./web
COPY fixtures ./fixtures
COPY scripts ./scripts
RUN python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 heatreserve && mkdir -p /data && chown -R heatreserve:heatreserve /app /data
USER heatreserve
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "heatreserve.api:app", "--host", "0.0.0.0", "--port", "8000"]
