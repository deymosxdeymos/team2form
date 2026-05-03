FROM ghcr.io/gleam-lang/gleam:nightly-erlang

WORKDIR /app

COPY gleam.toml manifest.toml ./
COPY src ./src

RUN gleam deps download
RUN gleam build

ENV PORT=8000
EXPOSE 8000

CMD ["gleam", "run", "-m", "team2form_gleam/api"]
