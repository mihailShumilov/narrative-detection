.PHONY: dev run test report clean install lint

# Install dependencies
install:
	pip install -r requirements.txt

# Run the Streamlit dashboard (development)
dev:
	streamlit run app/streamlit_app.py --server.port 8501

# Run the fortnightly analysis pipeline
run:
	python main.py

# Run pipeline with snapshot data (no API keys needed)
run-snapshot:
	python main.py --snapshot

# Run tests
test:
	python -m pytest tests/ -v --tb=short

# Run tests with coverage
test-cov:
	python -m pytest tests/ -v --cov=pipeline --cov=connectors --cov-report=term-missing

# Generate a report only
report:
	python main.py --date $(shell date +%Y-%m-%d)

# Launch with Docker
docker-up:
	docker compose up --build -d

# Stop Docker
docker-down:
	docker compose down

# Clean generated files
clean:
	rm -rf data/cache/*
	rm -rf reports/*.json reports/*.md
	rm -rf __pycache__ **/__pycache__
	rm -rf .pytest_cache .coverage htmlcov

# Lint
lint:
	python -m py_compile main.py
	python -m py_compile pipeline/runner.py
	python -m py_compile pipeline/scoring.py
	python -m py_compile pipeline/clustering.py
	python -m py_compile app/streamlit_app.py
