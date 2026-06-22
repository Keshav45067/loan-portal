PROTO_DIR = ../proto
OUT_DIR = ./generated
PROTO_FILES = doc_intelligence.proto common.proto llm.proto config_registry.proto

.PHONY: proto run docker clean install venv

venv:
	python3 -m venv venv

install: venv
	./venv/bin/pip install -r requirements.txt

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
	@echo "✅ Doc Intelligence gRPC stubs generated"

run:
	./venv/bin/python server.py

docker:
	docker build -t doc-intelligence .

clean:
	rm -rf $(OUT_DIR)/*.py $(OUT_DIR)/*.pyi
