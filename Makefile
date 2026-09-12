.PHONY: install run lint format test check

install:
	python -m pip install -r requirements-dev.txt

run:
	python main.py

lint:
	ruff check src tests main.py scripts

format:
	ruff format src tests main.py scripts

test:
	python -m unittest discover -s tests -v

check: lint test
