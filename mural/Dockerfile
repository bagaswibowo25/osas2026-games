# Built from the repo root: docker build -f mural/Dockerfile .
FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir aiohttp==3.14.3 segno==1.6.6
COPY mural/server.py ./
COPY mural/static/ ./static/
# Shared with Last Geeko Standing: Geeko, animations, background, music, sound effects, confetti
COPY standing/static/geeko.svg standing/static/geeko.css standing/static/bg.png standing/static/sound.js standing/static/confetti.js ./static/
COPY standing/static/music/ ./static/music/
COPY shared/base.css ./static/shared/
COPY shared/fonts/ ./static/shared/fonts/
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]
