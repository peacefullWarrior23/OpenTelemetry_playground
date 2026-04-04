FROM python:3.12-slim
WORKDIR /app
# Install uv
RUN pip install uv

# Copy dependency files first (for caching)
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --no-dev
COPY app/ .
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
