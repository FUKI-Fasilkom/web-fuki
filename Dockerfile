FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# build-essential/libpq-dev are no longer installed: psycopg2-binary and pillow
# both ship manylinux wheels, so nothing here compiles from source. Dropping the
# toolchain removes ~400MB from the image. Re-add them if a future dependency
# needs to build a C extension.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# STATIC_ROOT and MEDIA_ROOT. Created here so the named volumes mounted over them
# inherit the right ownership instead of being created by the daemon as root.
RUN mkdir -p /app/staticfiles /app/media

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
