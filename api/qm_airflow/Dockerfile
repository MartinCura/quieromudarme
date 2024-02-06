# TODO: switch to apache/slim-2.9.0-python3.12 and add whatever i need
FROM apache/airflow:2.8.3-python3.11 AS dev
# Workdir is /opt/airflow and stuff is run from /opt/airflow/dags

ENV POETRY_VERSION=1.8.2
ENV POETRY_HOME=/home/airflow/.local
ENV PYTHONPATH=/opt/app

USER 0
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,uid=0,gid=0 \
    --mount=type=cache,target=/var/lib/apt,sharing=locked,uid=0,gid=0 \
    apt update -yq && \
    apt install -yq \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libwayland-client0 libxcomposite1 libxdamage1 \
    libxfixes3 libxkbcommon0 libxrandr2 xdg-utils libu2f-udev libvulkan1 acl \
    sudo unzip wget curl xvfb gnupg && \
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

RUN pip install --no-cache-dir --upgrade pip && \
    curl -sSL https://install.python-poetry.org | PIP_USER=false python3 - && \
    poetry config virtualenvs.path $HOME/.local

COPY pyproject.toml poetry.lock /opt/app/
RUN --mount=type=cache,target=/home/airflow/.cache/pip,uid=50000,gid=0 \
    --mount=type=cache,target=/home/airflow/.cache/pypoetry,uid=50000,gid=0 \
    cd /opt/app && \
    python3 -m venv $HOME/.local && \
    source $HOME/.local/bin/activate && \
    poetry install --no-interaction --no-ansi --no-cache --with airflow --no-root
#   poetry run pip install  --constraint ./airflow-constraints.txt \
#       "apache-airflow==${AIRFLOW_VERSION}" apache-airflow-providers-postgres apache-airflow-providers-google
RUN cd /opt/app && \
    umask 0000 && \
    poetry run seleniumbase get chromedriver && \
    poetry run seleniumbase get uc_driver


FROM dev AS prod

COPY --chown=airflow:root ./pyproject.toml ./poetry.lock ./README.md /opt/app/
COPY --chown=airflow:root ./dist /opt/app/dist
RUN --mount=type=cache,target=/home/airflow/.cache/pip,uid=50000,gid=0 \
    --mount=type=cache,target=/home/airflow/.cache/pypoetry,uid=50000,gid=0 \
    cd /opt/app && \
    source $HOME/.local/bin/activate && \
    PIP_USER=false poetry run pip install ./dist/quieromudarme*.whl
