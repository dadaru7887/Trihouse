# 관제 UI를 브라우저용 정적 번들로 빌드해 nginx로 서빙한다.
#
# UI는 Gateway 주소를 **페이지 origin**에서 가져온다
# (`GatewayClientConfiguration.resolve`). 다른 origin을 쓰려면 HTTPS와
# credentialed cross-origin 모드가 필요하므로, P0에서는 nginx가 같은 origin에서
# `/api/`, `/health`, `/ready` 를 Gateway로 reverse proxy 한다. 그래야 브라우저가
# 설정 예외 없이 바로 동작한다.

# Flutter SDK 는 Google 아카이브에서 정확한 버전으로 직접 받는다.
# `ghcr.io/cirruslabs/flutter` 는 쓰지 않는다 — 그 미러는 3.44.0 까지만 올려
# 두었고, 3.44.0 의 Dart 는 3.12.0 이라 pubspec 의 `sdk: ^3.12.2` 를 만족하지
# 못한다. 아카이브는 버전과 체크섬을 모두 고정할 수 있다.
FROM debian:bookworm-slim AS build

ARG FLUTTER_VERSION=3.44.9
ARG FLUTTER_SHA256=a9120fa4a01048bdef438ddc3a2d4b7389662ea98a95db86eeaf10382bc4efcb

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git unzip xz-utils \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/flutter.tar.xz \
      "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
 && echo "${FLUTTER_SHA256}  /tmp/flutter.tar.xz" | sha256sum -c - \
 && tar -xJf /tmp/flutter.tar.xz -C /opt \
 && rm /tmp/flutter.tar.xz

ENV PATH="/opt/flutter/bin:${PATH}"

# 빌드는 root 로 돈다. Flutter 는 root 실행 시 git "dubious ownership" 으로
# 버전 판별에 실패하므로 SDK 경로를 안전 목록에 넣는다.
RUN git config --global --add safe.directory /opt/flutter \
 && flutter --version \
 && flutter config --no-analytics \
 && flutter precache --web

WORKDIR /src

# 의존성을 소스보다 먼저 받아 Docker layer cache를 쓴다.
COPY control_ui/rmf_control_ui/pubspec.yaml control_ui/rmf_control_ui/pubspec.lock ./
RUN flutter pub get

COPY control_ui/rmf_control_ui/ ./
RUN flutter build web --release

FROM nginx:1.27-alpine

# SPA 라우팅과 Gateway reverse proxy 설정.
COPY control_ui/rmf_control_ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/build/web /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=5s --timeout=3s --retries=20 --start-period=5s \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
