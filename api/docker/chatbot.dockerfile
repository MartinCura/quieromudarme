FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /uvx /bin/
ENV UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy
WORKDIR /app

RUN adduser --system app
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt update -yq && \
    DEBIAN_FRONTEND=noninteractive apt install --no-install-recommends --assume-yes && \
    apt install -yqq gcc curl sudo unzip wget xvfb gnupg && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt update -yq && \
    curl -LO https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install -yq ./google-chrome-stable_current_amd64.deb && \
    rm google-chrome-stable_current_amd64.deb* && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

COPY ./static/ /app/static

RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --no-install-project

RUN uv run seleniumbase get chromedriver && \
    uv run seleniumbase get uc_driver


FROM base AS dev

COPY pyproject.toml uv.lock README.md /app/
COPY quieromudarme /app/quieromudarme
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --group dev

# USER app
CMD ["uv", "run", "watchfiles", "--filter", "python", "'chatbot'", "quieromudarme/"]


FROM base AS prod
ENV UV_COMPILE_BYTECODE=1

COPY deploy/uv.toml /app/
COPY dist/ /app/dist
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/uv \
    uv pip install ./dist/quieromudarme-*.whl

# USER app
CMD ["uv", "run", "--no-sync", "chatbot"]

# TODO: do a .dockerignore with allowlist
