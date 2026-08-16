FROM python:3.12-slim-bookworm

# Keep Python output unbuffered so container logs are visible immediately.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN groupadd --system trihouse \
    && useradd --system --gid trihouse --home-dir /app trihouse

WORKDIR /app

# Install runtime dependencies before application code to preserve the build cache.
COPY fms_gateway/requirements.txt /tmp/requirements.txt
RUN python -m pip install --requirement /tmp/requirements.txt

COPY fms_gateway /app/fms_gateway
COPY control_tower/task_manager/__init__.py /app/control_tower/task_manager/__init__.py
COPY control_tower/task_manager/outbound_planner.py /app/control_tower/task_manager/outbound_planner.py
COPY control_tower/task_manager/outbound_sequence.py /app/control_tower/task_manager/outbound_sequence.py

USER trihouse

EXPOSE 8080 8788

CMD ["python", "-m", "uvicorn", "fms_gateway.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
