# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app --shell /usr/sbin/nologin app \
    && chown app:app /app

COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./

RUN pip install --upgrade pip && pip install .

# ---------------------------------------------------------------------------
# test: adds dev tooling (pytest, ruff, mypy, httpx) for CI and local
# container-based verification. Never used in production.
# ---------------------------------------------------------------------------
FROM base AS test

RUN pip install .[dev]
COPY --chown=app:app tests ./tests
COPY --chown=app:app compose.prod.yml ./
COPY --chown=app:app deploy ./deploy

USER app

CMD ["pytest"]

# ---------------------------------------------------------------------------
# runtime: minimal production image. No dev tooling, no test sources.
# ---------------------------------------------------------------------------
FROM base AS runtime

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
