# 관제 UI를 브라우저용 정적 번들로 빌드해 nginx로 서빙한다.
#
# UI는 Gateway 주소를 **페이지 origin**에서 가져온다
# (`GatewayClientConfiguration.resolve`). 다른 origin을 쓰려면 HTTPS와
# credentialed cross-origin 모드가 필요하므로, P0에서는 nginx가 같은 origin에서
# `/api/`, `/health`, `/ready` 를 Gateway로 reverse proxy 한다. 그래야 브라우저가
# 설정 예외 없이 바로 동작한다.

FROM ghcr.io/cirruslabs/flutter:3.44.9 AS build

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
