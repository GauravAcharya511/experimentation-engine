.PHONY: setup data build test dbt-run dbt-test dashboard clean

DBT = cd dbt && DBT_DATA_DIR=$(abspath data) dbt

setup:          ## create venv + install deps
	python3 -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r requirements.txt

data:           ## generate the synthetic experiment dataset
	python src/simulate.py

build: data     ## generate data, then run the dbt pipeline
	$(DBT) run --profiles-dir .

dbt-run:        ## run dbt models against existing data
	$(DBT) run --profiles-dir .

dbt-test:       ## run dbt data-quality tests
	$(DBT) test --profiles-dir .

test:           ## run the python test suite (Phase 3)
	pytest -q

dashboard:      ## launch the Streamlit readout (Phase 4)
	streamlit run app/main.py

clean:          ## remove generated data, warehouse, dbt artifacts, caches
	rm -f data/*.parquet dbt/dev.duckdb && rm -rf dbt/target dbt/logs __pycache__ src/__pycache__ .pytest_cache
