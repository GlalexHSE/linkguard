FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pika==1.3.2
COPY scanner.py blacklist.txt ./
RUN useradd --system app
USER app
CMD ["python", "-u", "scanner.py"]
