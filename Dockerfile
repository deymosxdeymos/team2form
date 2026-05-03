FROM ghcr.io/gleam-lang/gleam:v1.15.0-erlang-alpine AS builder

WORKDIR /app

COPY gleam.toml manifest.toml ./
COPY src ./src

RUN gleam deps download
RUN gleam build
RUN gleam export erlang-shipment

FROM erlang:28.0.2.0-alpine

WORKDIR /app

COPY --from=builder /app/build/erlang-shipment /app
COPY healthcheck.sh /app/healthcheck.sh

RUN addgroup -S team2form \
  && adduser -S -G team2form team2form \
  && chmod +x /app/entrypoint.sh /app/healthcheck.sh \
  && chown -R team2form:team2form /app

USER team2form
ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["/app/healthcheck.sh"]

CMD ["/app/entrypoint.sh", "run"]
