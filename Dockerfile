# One image per game: docker build --build-arg GAME=memory .
FROM nginx:1.27-alpine
ARG GAME
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY games/${GAME}/ /usr/share/nginx/html/
COPY shared/ /usr/share/nginx/html/shared/
