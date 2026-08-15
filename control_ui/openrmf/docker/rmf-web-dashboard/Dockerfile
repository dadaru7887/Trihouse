FROM ubuntu:24.04 AS build

ARG RMF_WEB_REF=7aa265337936a5bd9a920b3fa2360a43244a015c
ENV DEBIAN_FRONTEND=noninteractive
ENV PNPM_HOME=/root/.local/share/pnpm
ENV PATH="${PNPM_HOME}/bin:${PNPM_HOME}:${PATH}"

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libatomic1 \
    python3 \
    python3-venv \
  && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://get.pnpm.io/install.sh | bash - \
  && pnpm env use --global 20 \
  && pnpm self-update 9.15.9

RUN mkdir -p /ws \
  && curl -fsSL \
    "https://github.com/open-rmf/rmf-web/archive/${RMF_WEB_REF}.tar.gz" \
    -o /tmp/rmf-web.tar.gz \
  && tar -xzf /tmp/rmf-web.tar.gz -C /ws --strip-components=1

RUN cd /ws \
  && pnpm install --no-frozen-lockfile --filter rmf-dashboard-framework...

RUN cd /ws/packages/rmf-dashboard-framework \
  && pnpm build:example examples/demo

FROM nginx:1.27-alpine

COPY --from=build \
  /ws/packages/rmf-dashboard-framework/examples/demo/dist \
  /usr/share/nginx/html

EXPOSE 80
