FROM golang:1.25-alpine AS build

WORKDIR /src/goframe-backend
COPY goframe-backend/go.mod goframe-backend/go.sum ./
RUN go mod download
COPY goframe-backend/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/goframe-backend .

FROM alpine:3.22

RUN apk add --no-cache ca-certificates wget
WORKDIR /app/goframe-backend

COPY --from=build /out/goframe-backend ./goframe-backend
COPY goframe-backend/manifest ./manifest
COPY shared/sql /app/shared/sql

EXPOSE 8080
ENTRYPOINT ["./goframe-backend"]
