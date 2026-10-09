FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/agent ANONYMIZED_TELEMETRY=False \
    ECHOMIND_EXPERIMENT_DIR=/state/artifacts
WORKDIR /app
RUN useradd --create-home --uid 10001 agent && mkdir -p /state && chown agent:agent /state
COPY requirements-runtime.txt /app/requirements-runtime.txt
RUN pip install --no-cache-dir -r requirements-runtime.txt
COPY EchoMind/ /app/
RUN mkdir -p /home/agent/.cache && chown -R agent:agent /home/agent/.cache
USER 10001:10001
# Download and validate the public Chroma embedding model at build time.
# Runtime index creation deliberately fails if the frozen model is unavailable.
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2(preferred_providers=['CPUExecutionProvider'])(['model initialization'])"
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "experiments.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
