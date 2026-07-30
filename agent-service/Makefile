PROTO_DIR = ../proto
OUT_DIR = ./generated
PROTO_FILES = agent.proto doc_capture.proto

.PHONY: setup proto run clean

setup:
	python3 -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install -r requirements.txt
	$(MAKE) proto

proto:
	@mkdir -p $(OUT_DIR)
	@touch $(OUT_DIR)/__init__.py
	./venv/bin/python -m grpc_tools.protoc \
		-I$(PROTO_DIR) \
		--python_out=$(OUT_DIR) \
		--grpc_python_out=$(OUT_DIR) \
		--pyi_out=$(OUT_DIR) \
		$(addprefix $(PROTO_DIR)/, $(PROTO_FILES))
	@for f in $(OUT_DIR)/*_pb2_grpc.py; do \
		sed -i '' 's/^import \(.*\)_pb2/from . import \1_pb2/' "$$f" 2>/dev/null || \
		sed -i 's/^import \(.*\)_pb2/from . import \1_pb2/' "$$f"; \
	done
	@echo "✅ Agent Service gRPC stubs generated"

run: proto
	./venv/bin/python server.py

clean:
	rm -rf venv __pycache__ $(OUT_DIR)/*.py
