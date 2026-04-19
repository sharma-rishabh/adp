# Agentic Day Planner

A self-hosted agentic day planner and assistant with a sandboxed file environment, Telegram interface, and Claude as the AI backend.

## Setup

```bash
# Install dependencies
poetry install

# Copy env template and fill in your keys
cp .env.example .env

# Run the bot
poetry run planner
```

## Configuration

See `.env.example` for all available configuration options.

## Development

```bash
# Run tests
poetry run pytest

# Lint
poetry run ruff check src/ tests/

# Format
poetry run ruff format src/ tests/
```

