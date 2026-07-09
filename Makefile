.PHONY: setup data test dashboard clean

setup:          ## create venv + install deps
	python -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r requirements.txt

data:           ## generate the synthetic experiment dataset
	python src/simulate.py

test:           ## run the test suite
	pytest -q

dashboard:      ## launch the Streamlit experiment readout (Phase 4)
	streamlit run app/main.py

clean:          ## remove generated data + caches
	rm -f data/*.parquet && rm -rf __pycache__ src/__pycache__ .pytest_cache
