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
LLM Service gRPC Server — entry point.

Starts a gRPC server that implements the LanguageModel service.
All requests include req_id from gRPC metadata for tracing.
"""

import asyncio
import signal
import sys
import os
import traceback
import grpc
from grpc import aio as grpc_aio

# Add shared libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, extract_req_id, set_req_id

# Add generated stubs to path
sys.path.insert(0, os.path.dirname(__file__))

from generated import llm_pb2, llm_pb2_grpc, common_pb2
from service import LLMService
from config import LLM_SERVICE_PORT

logger = get_logger("llm-service")


class LanguageModelServicer(llm_pb2_grpc.LanguageModelServicer):
    """gRPC servicer implementing the LanguageModel service."""

    def __init__(self, service: LLMService):
        self._service = service

    async def Generate(self, request, context):
        """Unary text generation."""
        req_id = extract_req_id(context)
        logger.info("Generate called",
                     req_id=req_id,
                     model=request.model,
                     method="Generate")
        try:
            result = await self._service.generate(
                prompt=request.prompt,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                thinking_budget=request.thinking_budget,
                system_instruction=request.system_instruction,
                disable_thinking=request.disable_thinking,
            )
            return llm_pb2.GenerateResponse(
                text=result["text"],
                prompt_tokens=result.get("prompt_tokens", 0),
                completion_tokens=result.get("completion_tokens", 0),
            )
        except Exception as e:
            logger.error(f"Generate failed: {e}",
                         req_id=req_id, method="Generate",
                         error=traceback.format_exc())
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return llm_pb2.GenerateResponse()

    async def Extract(self, request, context):
        """Structured JSON extraction."""
        req_id = extract_req_id(context)
        logger.info("Extract called", req_id=req_id, model=request.model, method="Extract")
        try:
            result = await self._service.extract(
                prompt=request.prompt,
                model=request.model,
                temperature=request.temperature,
                system_instruction=request.system_instruction,
                thinking_budget=request.thinking_budget,
                disable_thinking=request.disable_thinking,
            )
            return llm_pb2.ExtractResponse(
                json_text=result.get("json_text", "{}"),
                success=result.get("success", False),
                error=result.get("error", ""),
            )
        except Exception as e:
            logger.error(f"Extract failed: {e}",
                         req_id=req_id, method="Extract",
                         error=traceback.format_exc())
            return llm_pb2.ExtractResponse(
                json_text="{}",
                success=False,
                error=str(e),
            )

    async def GenerateStream(self, request, context):
        """Server-side streaming text generation."""
        req_id = extract_req_id(context)
        logger.info("GenerateStream called",
                     req_id=req_id, model=request.model, method="GenerateStream")
        try:
            chunk_idx = 0
            async for text_chunk in self._service.generate_stream(
                prompt=request.prompt,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                thinking_budget=request.thinking_budget,
                system_instruction=request.system_instruction,
                disable_thinking=request.disable_thinking,
            ):
                chunk_idx += 1
                yield llm_pb2.TextChunk(text=text_chunk, is_last=False)

            # Send final empty chunk to signal completion
            yield llm_pb2.TextChunk(text="", is_last=True)
            logger.info("GenerateStream completed",
                         req_id=req_id, method="GenerateStream",
                         details={"total_chunks": chunk_idx})

        except Exception as e:
            logger.error(f"GenerateStream failed: {e}",
                         req_id=req_id, method="GenerateStream",
                         error=traceback.format_exc())
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))

    async def GenerateMultimodal(self, request, context):
        """Multimodal generation with images."""
        req_id = extract_req_id(context)
        logger.info("GenerateMultimodal called",
                     req_id=req_id, model=request.model, method="GenerateMultimodal",
                     details={"num_images": len(request.images)})
        try:
            result = await self._service.generate_multimodal(
                prompt=request.prompt,
                images=list(request.images),
                model=request.model,
                temperature=request.temperature,
                system_instruction=request.system_instruction,
                thinking_budget=request.thinking_budget,
                disable_thinking=request.disable_thinking,
            )
            return llm_pb2.GenerateResponse(
                text=result["text"],
                prompt_tokens=result.get("prompt_tokens", 0),
                completion_tokens=result.get("completion_tokens", 0),
            )
        except Exception as e:
            logger.error(f"GenerateMultimodal failed: {e}",
                         req_id=req_id, method="GenerateMultimodal",
                         error=traceback.format_exc())
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return llm_pb2.GenerateResponse()


async def serve():
    """Start the gRPC server."""
    server = grpc_aio.server(
        options=[
            ("grpc.max_send_message_length", 50 * 1024 * 1024),    # 50MB
            ("grpc.max_receive_message_length", 50 * 1024 * 1024),  # 50MB
        ]
    )

    # Initialize service
    service = LLMService()
    service.load()

    # Register servicer
    llm_pb2_grpc.add_LanguageModelServicer_to_server(
        LanguageModelServicer(service), server
    )

    listen_addr = f"[::]:{LLM_SERVICE_PORT}"
    server.add_insecure_port(listen_addr)

    logger.info(f"LLM Service starting on {listen_addr}",
                details={"port": LLM_SERVICE_PORT})

    await server.start()
    logger.info("LLM Service ready and accepting connections ✅")

    # Graceful shutdown
    async def shutdown(sig):
        logger.info(f"Received {sig.name}, shutting down...")
        await server.stop(grace=5)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
