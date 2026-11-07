FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.version="1.0.0" \
    org.opencontainers.image.licenses="GPL-3.0-only" \
    org.opencontainers.image.source="https://github.com/jadchene/pgr-bbs-sgin"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 基础镜像已包含证书和时区数据，构建时直接检查其可用性。
RUN python -c "import ssl; from zoneinfo import ZoneInfo; assert ssl.create_default_context().get_ca_certs(); ZoneInfo('Asia/Shanghai')" \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app
COPY app.py community.py supply.py mail_notify.py LICENSE NOTICE ./
USER 10001:10001
CMD ["python", "app.py"]
