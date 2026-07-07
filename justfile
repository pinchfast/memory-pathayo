# List available commands
default:
    @just --list

# Install dependencies
[group('setup')]
bootstrap:
    uv sync

# Set up the application for the first time after cloning
[group('setup')]
setup: bootstrap
    @if [ ! -f .env ]; then cp .env.template .env; echo "Created .env from template"; fi
    uv run python -m kgmemory migrate-db
    @echo "✓ Setup complete! Don't forget to:"
    @echo "  1. Configure your .env file"
    @echo "  2. Create your database: createdb kgmemory"
    @echo "  3. Run 'just migrate' to apply database migrations"

# Update dependencies to the latest versions
[group('setup')]
update:
    uv sync --upgrade

# Start the development server
[group('dev')]
server:
    uv run python -m kgmemory run-server

# Run all development services (server, worker, redis, falkordb)
[group('dev')]
work:
    uv run python -m kgmemory work

# Run the full stack via docker compose
[group('dev')]
compose-up:
    docker compose up --build

# Stop the docker compose stack
[group('dev')]
compose-down:
    docker compose down

# Run tests
[group('dev')]
test *ARGS:
    uv run pytest kgmemory/ {{ARGS}}

# Open an interactive console
[group('dev')]
console:
    uv run python -m kgmemory shell

# Apply database migrations
[group('database')]
migrate:
    uv run python -m kgmemory migrate-db

# Create a new database migration
[group('database')]
makemigrations NAME:
    uv run aerich migrate --name {{NAME}}

# Initialize the database
[group('database')]
init-db:
    uv run aerich init-db

# Create a new user interactively
[group('utils')]
create-user:
    uv run python -m kgmemory create-user

# Generate a secure secret key
[group('utils')]
secret-key:
    uv run python -m kgmemory secret-key

# Show project health and settings information
[group('utils')]
info:
    uv run python -m kgmemory info

# Create a new FastAPI app/component
[group('utils')]
start-app NAME:
    uv run python -m kgmemory start-app {{NAME}}

# Run the SAQ worker
[group('services')]
worker:
    uv run python -m kgmemory run-worker

# Run a test mail server for development
[group('services')]
mailserver:
    uv run python -m kgmemory run-mailserver

# Run the production server with gunicorn
[group('services')]
prod-server:
    uv run python -m kgmemory run-prod-server

# Run linting and formatting checks
[group('quality')]
lint:
    uv run ruff check .

# Format code with black and isort
[group('quality')]
format:
    uv run ruff format .
    uv run ruff check --fix .

# Clean up temporary files and caches
[group('maintenance')]
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete
    find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
