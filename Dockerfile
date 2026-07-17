FROM python:3.12-slim

WORKDIR /srv/rxguard

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

COPY app ./app
COPY data ./data
COPY demo ./demo

ENV PATH="/srv/rxguard/.venv/bin:$PATH"
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
