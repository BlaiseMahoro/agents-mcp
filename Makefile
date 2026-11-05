.PHONY: setup sandbox search api web dev test mcp

setup:            ## install backend + frontend deps, build sandbox, start SearXNG
	cd backend && uv sync
	cd frontend && npm install
	$(MAKE) sandbox search

sandbox:          ## build the Docker image plans run in
	docker compose build sandbox

search:           ## start SearXNG (web search for open models) on :8888
	docker compose up -d searxng

api:              ## FastAPI backend on :8000
	cd backend && uv run uvicorn agents_core.api.main:app --host 127.0.0.1 --port 8000 --reload

web:              ## Next.js chat UI on :3000
	cd frontend && npm run dev

dev:              ## backend + frontend together
	$(MAKE) -j2 api web

test:             ## backend tests (the Docker test is skipped if Docker is down)
	cd backend && uv run pytest -q

mcp:              ## MCP server over stdio
	cd backend && uv run agents-mcp
