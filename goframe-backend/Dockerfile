FROM golang:1.25.11-alpine AS build

WORKDIR /src/goframe-backend
COPY goframe-backend/go.mod goframe-backend/go.sum ./
RUN go mod download
COPY goframe-backend/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/goframe-backend .

FROM alpine:3.22

RUN apk add --no-cache ca-certificates mysql-client wget \
    && addgroup -S knowmate \
    && adduser -S -D -H -u 10001 -G knowmate knowmate \
    && mkdir -p /app/shared/outputs
WORKDIR /app/goframe-backend

COPY --from=build /out/goframe-backend ./goframe-backend
COPY goframe-backend/manifest ./manifest
COPY shared/sql /app/shared/sql
COPY scripts/run_migrations.sh /app/scripts/run_migrations.sh

RUN chmod +x ./goframe-backend /app/scripts/run_migrations.sh \
    && chown -R knowmate:knowmate /app

EXPOSE 8080
USER knowmate
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/health >/dev/null || exit 1
ENTRYPOINT ["./goframe-backend"]
