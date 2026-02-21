.PHONY: help install run-api run-dashboard run-phoenix seed lint

help: ## Show available commands
	@echo ""
	@echo "LLM Observability Dashboard"
	@echo "==========================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

install: ## Install all Python dependencies
	pip install -r requirements.txt

setup: ## Copy .env.example to .env (run once after clone)
	@test -f .env || (cp .env.example .env && echo "Created .env — add your ANTHROPIC_API_KEY")

seed: ## Seed the database with 500 synthetic sample records
	python scripts/seed_data.py

run-api: ## Start the FastAPI backend on :8000
	uvicorn llm_observability.main:app --host 0.0.0.0 --port 8000 --reload

run-dashboard: ## Start the Streamlit dashboard on :8501
	streamlit run llm_observability/dashboard/app.py

run-phoenix: ## Launch Arize Phoenix tracing UI on :6006 (optional)
	python -c "import phoenix as px; session = px.launch_app(); print('Phoenix UI:', session.url); import time; time.sleep(86400)"

dev: ## Start both API and dashboard (requires tmux or two terminals)
	@echo "Run in separate terminals:"
	@echo "  Terminal 1: make run-api"
	@echo "  Terminal 2: make run-dashboard"
	@echo "  (Optional) Terminal 3: make run-phoenix"
