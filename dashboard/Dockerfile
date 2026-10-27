ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}
WORKDIR /app
COPY server.py gitcode_auth.py /app/
COPY static /app/static
ENV PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["python3", "/app/server.py"]
