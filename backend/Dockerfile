FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY data /app/data
COPY scripts /app/scripts

RUN mkdir -p /data/runtime /data/releases /sequence_info

ENV DJANGO_SECRET_KEY=build-time-openkinetics-data-secret-key
ENV DJANGO_DEBUG=0
ENV SQLITE_PATH=/tmp/openkinetics-build.sqlite3
ENV OPENKINETICS_RELEASES_ROOT=/data/releases
ENV OPENKINETICS_SEQUENCE_INFO_ROOT=/sequence_info

RUN python backend/manage.py collectstatic --noinput

EXPOSE 8010

CMD ["gunicorn", "openkinetics_data.wsgi:application", "--chdir", "/app/backend", "--bind", "0.0.0.0:8010", "--workers", "3", "--timeout", "180"]
