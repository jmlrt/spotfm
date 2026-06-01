FROM python:3.14-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
COPY spotfm/ spotfm/
RUN uv pip install --no-cache-dir --system ".[web]"
EXPOSE 8000
CMD ["uvicorn", "spotfm.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
