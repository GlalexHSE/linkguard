FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]==3.2.3"
COPY watchdog.py .
RUN useradd --system app
USER app
CMD ["python", "-u", "watchdog.py"]
