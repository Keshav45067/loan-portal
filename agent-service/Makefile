.PHONY: setup run clean

setup:
	python3 -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install -r requirements.txt

run:
	./venv/bin/uvicorn server:app --host 0.0.0.0 --port 8090 --reload

clean:
	rm -rf venv __pycache__
