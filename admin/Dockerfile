# Built from the repo root: docker build -f admin/Dockerfile .
FROM python:3.13-alpine
WORKDIR /app
COPY admin/server.py admin/scores.py ./
COPY admin/static/ ./static/
COPY shared/base.css ./static/shared/
COPY shared/fonts/ ./static/shared/fonts/
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]
