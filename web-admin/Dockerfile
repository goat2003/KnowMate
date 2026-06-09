FROM node:24-alpine AS build

WORKDIR /src/web-admin
COPY web-admin/package*.json ./
RUN npm ci
COPY web-admin/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY web-admin/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/web-admin/dist /usr/share/nginx/html

EXPOSE 8080
USER nginx
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1
