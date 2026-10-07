# Built from the repo root: docker build -f standing/Dockerfile .
FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir aiohttp==3.14.3 segno==1.6.6
COPY standing/server.py ./
COPY standing/static/ ./static/
COPY shared/base.css ./static/shared/
COPY shared/fonts/ ./static/shared/fonts/
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]
