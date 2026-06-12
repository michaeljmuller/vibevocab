ARG PG_VERSION=16
FROM debian:bookworm-slim
RUN apt-get update -qq \
    && apt-get install -y -qq curl awscli gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update -qq \
    && apt-get install -y -qq postgresql-client-${PG_VERSION} \
    && rm -rf /var/lib/apt/lists/*
