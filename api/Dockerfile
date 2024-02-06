FROM python:3.12-slim AS base
WORKDIR /opt/app

ENV POETRY_VERSION=1.8.2
ENV POETRY_HOME=/usr/local

USER root

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

RUN pip install --no-cache-dir --upgrade pip && \
    curl -sSL https://install.python-poetry.org | PIP_USER=false python3 - && \
    poetry config virtualenvs.create false

COPY ./static/ /opt/app/static

COPY pyproject.toml poetry.lock README.md /opt/app/
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --no-interaction --no-cache --no-root
RUN poetry run seleniumbase get chromedriver && \
    poetry run seleniumbase get uc_driver
# USER 1000


FROM base AS dev

COPY ./dev_entrypoint.sh /opt/app/dev_entrypoint.sh
RUN poetry install --only dev

ENTRYPOINT ["/opt/app/dev_entrypoint.sh"]
CMD ["watchfiles", "--filter", "python", "'chatbot'", "quieromudarme/"]


FROM base AS prod

COPY dist/ /opt/app/dist
# RUN poetry install -vv --no-interaction --only-root
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/pypoetry \
    poetry run pip install ./dist/quieromudarme*.whl
# USER 1000

CMD ["chatbot"]

# TODO: do a .dockerignore with allowlist
