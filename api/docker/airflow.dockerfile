FROM apache/airflow:2.10.5-python3.12 AS base
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /uvx /bin/
# Workdir is /opt/airflow and stuff is run from /opt/airflow/dags
ENV APP_PYTHON_BIN=/app/.venv/bin/python \
    PYTHONPATH=/app \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy

USER 0
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,uid=0,gid=0 \
    --mount=type=cache,target=/var/lib/apt,sharing=locked,uid=0,gid=0 \
    apt update -yq && \
    apt install -yq \
        fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libcups2 libdbus-1-3 \
        libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libwayland-client0 libxcomposite1 libxdamage1 \
        libxfixes3 libxkbcommon0 libxrandr2 xdg-utils libu2f-udev libvulkan1 acl \
        unzip wget curl xvfb gnupg sudo && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,uid=0,gid=0 \
    --mount=type=cache,target=/var/lib/apt,sharing=locked,uid=0,gid=0 \
    apt update -yq && \
    curl -LO https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install -yq ./google-chrome-stable_current_amd64.deb && \
    rm google-chrome-stable_current_amd64.deb && \
    mkdir -p /home/airflow/.config/google-chrome && \
    chown airflow:root /home/airflow/.config && \
    chown 1000:root /home/airflow/.config/google-chrome && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*
USER airflow

WORKDIR /app
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# RUN umask 0000 && \
#     uv run --no-sync seleniumbase get chromedriver && \
#     uv run --no-sync seleniumbase get uc_driver


FROM base AS dev

WORKDIR /app
COPY pyproject.toml uv.lock README.md /app/
COPY quieromudarme /app/quieromudarme
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --group dev --group etl
WORKDIR /opt/airflow


FROM base AS prod
ENV UV_COMPILE_BYTECODE=1

WORKDIR /app
COPY pyproject.toml uv.lock deploy/uv.toml README.md /app/
COPY dist /app/dist
COPY quieromudarme/etl/dags /opt/airflow/dags
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group etl
WORKDIR /opt/airflow

# TODO: clean up
# COPY --chown=airflow:root ./pyproject.toml ./uv.lock ./README.md /app/
# COPY --chown=airflow:root ./dist /app/dist
# RUN --mount=type=cache,target=/home/airflow/.cache/pip,uid=50000,gid=0 \
#     --mount=type=cache,target=/home/airflow/.cache/uv,uid=50000,gid=0 \
#     cd /app && \
#     source $HOME/.local/bin/activate && \
#     PIP_USER=false uv pip install ./dist/quieromudarme-*.whl
