FROM python:3.12-slim-bookworm

# Python 바이트코드를 남기지 않고 로그를 즉시 컨테이너 stdout으로 내보낸다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN groupadd --system trihouse \
    && useradd --system --gid trihouse --home-dir /app trihouse

WORKDIR /app

# 의존성을 소스보다 먼저 복사해 애플리케이션 변경 시에도 Docker layer cache를 쓴다.
COPY fms_gateway/requirements.txt /tmp/requirements.txt
RUN python -m pip install --requirement /tmp/requirements.txt

COPY fms_gateway /app/fms_gateway
COPY control_tower/task_manager/__init__.py /app/control_tower/task_manager/__init__.py
COPY control_tower/task_manager/outbound_planner.py /app/control_tower/task_manager/outbound_planner.py
COPY control_tower/task_manager/outbound_sequence.py /app/control_tower/task_manager/outbound_sequence.py

# DB/TCP 자격 증명에 문제가 생겨도 root 권한으로 확산되지 않도록 한다.
USER trihouse

# 8080은 HTTP API, 8788은 로봇 NDJSON TCP 수집 포트다.
EXPOSE 8080 8788

# factory 모드로 환경 설정과 Repository를 프로세스 시작 시 구성한다.
CMD ["python", "-m", "uvicorn", "fms_gateway.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
