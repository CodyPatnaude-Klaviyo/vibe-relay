.PHONY: up server ui install lint test

# Start both API server and UI dev server (requires two terminals)
up:
	@echo "Run in separate terminals:"
	@echo "  make server   # Terminal 1 — API on :8000"
	@echo "  make ui       # Terminal 2 — UI on :5173"

# API server only
server:
	vibe-relay serve

# UI dev server only
ui:
	cd ui && npm run dev

# Install all dependencies
install:
	uv pip install -e ".[dev]"
	cd ui && npm install

# Run all lints and checks
lint:
	ruff check .
	ruff format --check .
	mypy vibe_relay/ api/ db/ runner/
	cd ui && npm run typecheck && npm run lint

# Run all tests
test:
	uv run pytest tests/ -v
	cd ui && npm run build
