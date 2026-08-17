# Force IPv4 resolution to bypass macOS IPv6 network blackhole for external APIs
import socket
_original_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(*args, **kwargs):
    try:
        res = _original_getaddrinfo(*args, **kwargs)
        filtered = [r for r in res if r[0] == socket.AF_INET]
        return filtered if filtered else res
    except Exception:
        return _original_getaddrinfo(*args, **kwargs)
socket.getaddrinfo = _ipv4_only_getaddrinfo

"""
Config Registry gRPC Server — entry point.

Loads YAML configs → Redis → serves via gRPC.
All consumers (Voice Engine, Orchestrator, Doc Intel) call this once
at session start and cache the response in-process.
"""

import asyncio
import signal
import sys
import os
import json
import traceback

import grpc
from grpc import aio as grpc_aio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, extract_req_id, LatencyTracker

sys.path.insert(0, os.path.dirname(__file__))

from generated import config_registry_pb2 as pb2
from generated import config_registry_pb2_grpc as pb2_grpc
from service import ConfigService
from cache import RedisCache
from config import CONFIG_REGISTRY_PORT

logger = get_logger("config-registry")


def _dict_to_graph_node(node_id: str, node_data: dict) -> pb2.GraphNode:
    """Convert YAML node dict to protobuf GraphNode."""
    edges = []
    for edge in node_data.get("edges", []):
        edges.append(pb2.GraphEdge(
            condition=edge.get("condition", "always"),
            next_node_id=edge.get("next", ""),
        ))

    text_templates = {}
    for k, v in node_data.items():
        if k.startswith("text_template_") and isinstance(v, str):
            lang = k[len("text_template_"):]
            text_templates[lang] = v
    if "text_template" in node_data and isinstance(node_data["text_template"], str):
        text_templates["hi"] = node_data["text_template"]

    validation_data = node_data.get("validation", {})
    validation_json = json.dumps(validation_data) if validation_data else ""

    return pb2.GraphNode(
        node_id=node_id,
        text_template=node_data.get("text_template", ""),
        targets=node_data.get("targets", []),
        edges=edges,
        routing_prompt=node_data.get("routing_prompt", ""),
        type=node_data.get("type", "voice-qa"),
        document_id=node_data.get("document_id", ""),
        text_template_en=node_data.get("text_template_en", ""),
        text_template_te=node_data.get("text_template_te", ""),
        text_template_fr=node_data.get("text_template_fr", ""),
        text_template_ar=node_data.get("text_template_ar", ""),
        text_templates=text_templates,
        validation_json=validation_json,
    )


def _dict_to_interview_graph(data: dict) -> pb2.InterviewGraph:
    """Convert YAML graph dict to protobuf InterviewGraph."""
    nodes = {}
    for node_id, node_data in data.get("nodes", {}).items():
        nodes[node_id] = _dict_to_graph_node(node_id, node_data)

    context_map = {}
    for node_id, deps in data.get("context_map", {}).items():
        context_map[node_id] = pb2.ContextDeps(dependencies=deps or [])

    return pb2.InterviewGraph(
        scheme_id=data.get("scheme_id", ""),
        nodes=nodes,
        start_node_id=data.get("start_node_id", "START"),
        context_map=context_map,
    )


def _dict_to_media_config(data: dict) -> pb2.MediaConfig:
    """Convert media config dict to protobuf."""
    return pb2.MediaConfig(
        scheme_id=data.get("scheme_id", ""),
        language=data.get("language", ""),
        tts_voice_name=data.get("tts_voice_name", ""),
        tts_engine=data.get("tts_engine", "google"),
        tts_sample_rate=data.get("tts_sample_rate", 24000),
        stt_engine=data.get("stt_engine", "google"),
        stt_language_code=data.get("stt_language_code", ""),
    )


def _dict_to_financial_rules(data: dict) -> pb2.FinancialRules:
    """Convert financial rules dict to protobuf."""
    inv = data.get("inventory_multiplier", {})
    profit = data.get("profit_margin", {})
    wcm = data.get("working_cycle_months", {})

    return pb2.FinancialRules(
        scheme_id=data.get("scheme_id", ""),
        inventory_multiplier=pb2.RangeRule(
            min=inv.get("min", 3), max=inv.get("max", 4)
        ),
        profit_margin=pb2.RangeRule(
            min=profit.get("min", 0.4), max=profit.get("max", 0.6)
        ),
        working_cycle_months={k: int(v) for k, v in wcm.items()},
        max_loan_amount=data.get("max_loan_amount", 1000000),
        promoter_contribution_pct=data.get("promoter_contribution_pct", 0.25),
        term_loan_pct=data.get("term_loan_pct", 0.90),
    )


def _dict_to_doc_requirements(data: dict) -> pb2.DocumentRequirements:
    """Convert doc requirements dict to protobuf."""
    docs = []
    for doc in data.get("documents", []):
        schema_dict = doc.get("schema", {})
        schema_str = json.dumps(schema_dict, ensure_ascii=False) if schema_dict else ""
        docs.append(pb2.DocumentRequirement(
            document_type=doc.get("type", ""),
            verify_prompt=doc.get("verify_prompt", ""),
            extract_prompt=doc.get("extract_prompt", ""),
            required=doc.get("required", True),
            max_pages=doc.get("max_pages", 1),
            schema_json=schema_str,
        ))
    return pb2.DocumentRequirements(
        scheme_id=data.get("scheme_id", ""),
        documents=docs,
    )


class ConfigRegistryServicer(pb2_grpc.ConfigRegistryServicer):
    """gRPC servicer implementing the ConfigRegistry service."""

    def __init__(self, service: ConfigService):
        self._service = service

    async def GetSchemeConfig(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetSchemeConfig", req_id=req_id, scheme_id=request.scheme_id)

        config = await self._service.get_scheme_config(request.scheme_id)
        if not config:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Scheme '{request.scheme_id}' not found")
            return pb2.SchemeConfig()

        # Build full protobuf response
        graph = config.get("interview_graph", {})
        graph["scheme_id"] = request.scheme_id
        graph["context_map"] = config.get("context_map", {})

        field_instructions = {}
        for name, instruction in config.get("field_instructions", {}).items():
            field_instructions[name] = pb2.FieldInstruction(
                field_name=name, instruction=instruction
            )

        media_configs = {}
        for lang in config.get("languages", []):
            mc = await self._service.get_media_config(request.scheme_id, lang)
            if mc:
                media_configs[lang] = _dict_to_media_config(mc)

        financial_data = config.get("financial_rules", {})
        financial_data["scheme_id"] = request.scheme_id

        doc_data = {
            "scheme_id": request.scheme_id,
            "documents": config.get("documents_required", []),
        }

        return pb2.SchemeConfig(
            scheme_id=request.scheme_id,
            display_name=config.get("display_name", ""),
            languages=config.get("languages", []),
            interview_graph=_dict_to_interview_graph(graph),
            document_requirements=_dict_to_doc_requirements(doc_data),
            field_instructions=field_instructions,
            financial_rules=_dict_to_financial_rules(financial_data),
            media_configs=media_configs,
            db_mapping=config.get("db_mapping", {}),
            system_voice_messages_json=json.dumps(config.get("system_voice_messages", {}), ensure_ascii=False) if config.get("system_voice_messages") else "",
        )

    async def GetInterviewGraph(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetInterviewGraph", req_id=req_id, scheme_id=request.scheme_id)

        graph_data = await self._service.get_interview_graph(request.scheme_id)
        if not graph_data:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Scheme '{request.scheme_id}' not found")
            return pb2.InterviewGraph()

        return _dict_to_interview_graph(graph_data)

    async def GetDocumentRequirements(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetDocumentRequirements", req_id=req_id, scheme_id=request.scheme_id)

        data = await self._service.get_document_requirements(request.scheme_id)
        if not data:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return pb2.DocumentRequirements()

        return _dict_to_doc_requirements(data)

    async def GetFieldInstruction(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetFieldInstruction", req_id=req_id,
                     scheme_id=request.scheme_id,
                     details={"field": request.field_name})

        data = await self._service.get_field_instruction(
            request.scheme_id, request.field_name
        )
        if not data:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return pb2.FieldInstruction()

        return pb2.FieldInstruction(
            field_name=data["field_name"],
            instruction=data["instruction"],
        )

    async def GetFinancialRules(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetFinancialRules", req_id=req_id, scheme_id=request.scheme_id)

        data = await self._service.get_financial_rules(request.scheme_id)
        if not data:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return pb2.FinancialRules()

        return _dict_to_financial_rules(data)

    async def GetMediaConfig(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetMediaConfig", req_id=req_id,
                     scheme_id=request.scheme_id, language=request.language)

        data = await self._service.get_media_config(
            request.scheme_id, request.language
        )
        if not data:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return pb2.MediaConfig()

        return _dict_to_media_config(data)

    async def CreateScheme(self, request, context):
        req_id = extract_req_id(context)
        logger.info("CreateScheme", req_id=req_id, scheme_id=request.scheme_id)

        # Convert protobuf to dict — for now, just store the basic fields
        config = {"scheme_id": request.scheme_id, "display_name": request.display_name,
                  "languages": list(request.languages)}
        result = await self._service.create_scheme(config)

        return pb2.SchemeResponse(
            success=result["success"],
            scheme_id=result.get("scheme_id", ""),
            error=result.get("error", ""),
        )

    async def UpdateScheme(self, request, context):
        req_id = extract_req_id(context)
        logger.info("UpdateScheme", req_id=req_id, scheme_id=request.scheme_id)

        config = {"scheme_id": request.scheme_id, "display_name": request.display_name,
                  "languages": list(request.languages)}
        result = await self._service.update_scheme(config)

        return pb2.SchemeResponse(
            success=result["success"],
            scheme_id=result.get("scheme_id", ""),
            error=result.get("error", ""),
        )

    async def ListSchemes(self, request, context):
        req_id = extract_req_id(context)
        logger.info("ListSchemes", req_id=req_id)

        summaries = await self._service.list_schemes()
        proto_summaries = []
        for s in summaries:
            proto_summaries.append(pb2.SchemeSummary(
                scheme_id=s["scheme_id"],
                display_name=s["display_name"],
                languages=s["languages"],
                total_nodes=s["total_nodes"],
            ))

        return pb2.SchemeList(schemes=proto_summaries)

    async def DeleteScheme(self, request, context):
        req_id = extract_req_id(context)
        logger.info("DeleteScheme", req_id=req_id, scheme_id=request.scheme_id)

        result = await self._service.delete_scheme(request.scheme_id)
        return pb2.SchemeResponse(
            success=result["success"],
            scheme_id=result.get("scheme_id", ""),
            error=result.get("error", ""),
        )


async def serve():
    """Start the Config Registry gRPC server."""
    # Initialize Redis cache
    cache = RedisCache()
    await cache.connect()

    # Initialize service and load configs
    service = ConfigService(cache)
    await service.load_configs()

    # Start gRPC server
    server = grpc_aio.server()
    pb2_grpc.add_ConfigRegistryServicer_to_server(
        ConfigRegistryServicer(service), server
    )

    listen_addr = f"[::]:{CONFIG_REGISTRY_PORT}"
    server.add_insecure_port(listen_addr)

    logger.info(f"Config Registry starting on {listen_addr}",
                details={"port": CONFIG_REGISTRY_PORT,
                          "redis": cache.is_available})

    await server.start()
    logger.info("Config Registry ready ✅")

    async def shutdown(sig):
        logger.info(f"Received {sig.name}, shutting down...")
        await server.stop(grace=5)
        await cache.close()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
