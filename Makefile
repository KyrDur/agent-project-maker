.PHONY: check check-backend check-frontend install
.NOTPARALLEL:

# One serial, reproducible quality gate for local development and CI.
check: install check-backend check-frontend

install:
	uv sync --directory backend --frozen --all-extras
	pnpm install --frozen-lockfile

check-backend:
	uv run --directory backend ruff check .
	uv run --directory backend ruff format --check .
	uv run --directory backend pyright
	uv run --directory backend pytest -q

check-frontend:
	pnpm --dir frontend lint
	pnpm --dir frontend lint:i18n
	pnpm --dir frontend lint:type-safety
	pnpm --dir frontend lint:e2e-hygiene
	pnpm --dir frontend lint:a11y
	pnpm --dir frontend lint:design-system
	pnpm --dir frontend lint:frontend-architecture:strict
	pnpm --dir frontend format:check
	pnpm --dir frontend test --run
	pnpm --dir frontend build
