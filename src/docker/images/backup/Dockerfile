FROM debian:bookworm-slim
RUN apt-get update -qq \
    && apt-get install -y -qq curl awscli postgresql-client \
    && rm -rf /var/lib/apt/lists/*
