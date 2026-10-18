FROM ghcr.io/astral-sh/uv:0.12.21 AS uv

FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend ./backend

RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

