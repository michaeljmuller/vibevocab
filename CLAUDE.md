# VibeVocab

A vocabulary-building flashcard web app.

## Runtime Environment

All services run in Docker containers orchestrated with Docker Compose.

- Production: Linux / x86-64 (intel)
- Development: macOS / arm64 (Apple Silicon)

Docker images must support both platforms (linux/amd64 for prod, arm64 for local dev).

Assume docker is already installed; every other dependency should be installed in containers.

## Documentation

- Use plain text (.txt) for all documentation files.
- Be concise.
