# --- Front : build Vue -------------------------------------------------------
FROM oven/bun:1.4 AS web
WORKDIR /src
COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/
RUN bun install --frozen-lockfile
COPY apps/web apps/web
# vue-tsc a besoin de Node (absent de l'image bun) : le typecheck se fait en dev/CI (bun run typecheck)
RUN cd apps/web && bunx --bun vite build

# --- API : Python + uv -------------------------------------------------------
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /src/apps/web/dist /app/web

ENV PATH="/opt/venv/bin:$PATH" \
    SOULSICK_CONFIG_DIR=/config \
    SOULSICK_MUSIC_DIR=/music \
    SOULSICK_DOWNLOADS_DIR=/downloads \
    SOULSICK_WEB_DIST=/app/web \
    SOULSICK_PORT=5030

VOLUME ["/config", "/music", "/downloads"]
# 5030 : interface web — 50300/50301 : port d'écoute Soulseek (+ obfuscation)
EXPOSE 5030 50300 50301
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5030/api/auth/state')"
CMD ["soulsick"]
