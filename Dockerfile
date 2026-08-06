FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY motif_cycles ./motif_cycles
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/workspace \
    && chown -R appuser:appuser /app/workspace
USER appuser

EXPOSE 8002
CMD ["motif-cycles"]
