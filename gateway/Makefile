PROTO_DIR = ../proto
OUT_DIR = ./grpc_clients/generated
# Gateway needs stubs for ALL services it connects to
PROTO_FILES = llm.proto stt.proto tts.proto config_registry.proto doc_intelligence.proto voice_engine.proto app_orchestrator.proto common.proto

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
	@echo "✅ Gateway gRPC stubs generated (all services)"

run:
	./venv/bin/python main.py

docker:
	docker build -t gateway .

clean:
	rm -rf $(OUT_DIR)/*.py $(OUT_DIR)/*.pyi
