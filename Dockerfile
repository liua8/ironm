# 用 Docker 跑 IronM（spec §185）：docker compose up -d 时由 compose.yaml 构建，不用单独跑这个文件。
# 国内下载慢时，.env 里的 DOCKER_MIRROR（镜像加速前缀）、PIP_INDEX_URL（Python 包源）、
# APT_MIRROR（系统包源，比如 mirrors.aliyun.com）会经 compose 传进来。
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG APT_MIRROR=
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_INDEX_URL=${PIP_INDEX_URL} \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH
RUN if [ -n "$APT_MIRROR" ]; then sed -i "s#deb.debian.org#${APT_MIRROR}#g" /etc/apt/sources.list.d/debian.sources; fi \
    && apt-get update && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --timeout 120 --retries 5 uv==0.13.1
WORKDIR /app

# 先只装依赖（版本照 uv.lock），改代码时这一层不用重来
COPY pyproject.toml uv.lock ./
COPY vendor/mirobody/pyproject.toml vendor/mirobody/pyproject.toml
RUN uv export --frozen --no-dev --no-emit-project --no-emit-package mirobody -o /tmp/requirements.txt \
    && uv venv /app/.venv \
    && uv pip install --no-cache -r /tmp/requirements.txt

# mirobody 和 iron-m 本身（可编辑安装，目录摆法和 scripts/start.sh 一样）
COPY vendor/mirobody vendor/mirobody
COPY docker/lfs.sh docker/lfs.sh
RUN sh docker/lfs.sh
COPY ironm_agent ironm_agent
COPY config config
COPY scripts scripts
COPY LICENSE README.md ./
RUN uv pip install --no-cache --no-deps -e vendor/mirobody -e . \
    && cd / && python -c 'import mirobody, ironm_agent.server, ironm_agent.web' \
    && chmod -R a+rX /app   # 宿主机上 umask 077 拿下来的代码是 600，容器里的 ironm 用户读不了


FROM ${PYTHON_IMAGE}
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then sed -i "s#deb.debian.org#${APT_MIRROR}#g" /etc/apt/sources.list.d/debian.sources; fi \
    && apt-get update && apt-get install -y --no-install-recommends curl ca-certificates fontconfig fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app /app
COPY --chmod=755 docker/entrypoint.sh /app/docker/entrypoint.sh
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    IRONM_DATA_DIR=/data
# 固定的 uid / gid：数据卷按编号认主人
RUN groupadd --system --gid 10001 ironm \
    && useradd --system --uid 10001 --gid 10001 --create-home ironm \
    && mkdir -p /data /secrets/pg /secrets/keys /app/vendor/mirobody/.theta \
    && chown -R ironm:ironm /data /app/vendor/mirobody/.theta
WORKDIR /app
USER ironm
EXPOSE 18090
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=30 \
    CMD curl -fsS -o /dev/null http://127.0.0.1:18090/iron/ || exit 1
ENTRYPOINT ["bash", "/app/docker/entrypoint.sh"]
CMD ["serve"]
