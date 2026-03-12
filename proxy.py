"""Claude Code API proxy — compresses message history on every request."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from compression import compress_messages
from stats import log_request

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
UPSTREAM = "https://api.anthropic.com"

logger = logging.getLogger("proxy")

from typing import Optional

http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=600, write=30, pool=10),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    yield
    await http_client.aclose()


app = FastAPI(lifespan=lifespan)

# Headers that must not be forwarded from upstream responses
_STRIP_RESPONSE_HEADERS = {
    "content-encoding", "transfer-encoding", "content-length", "connection",
}


@app.post("/v1/messages")
async def messages(request: Request):
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(content=body, status_code=400)

    messages_list = payload.get("messages", [])
    model = payload.get("model", "")

    # Run compression in a thread to avoid blocking the event loop
    compressed, stats = await asyncio.to_thread(compress_messages, messages_list)
    payload["messages"] = compressed

    saved = stats.get("saved_chars", 0)
    log_request(model, stats)
    if saved > 0:
        logger.info(
            "compressed %s: -%s chars (-%s tokens est) | rules: %s",
            model, f"{saved:,}", f"{stats['saved_tokens_est']:,}", stats["rules"],
        )

    headers = _upstream_headers(request)
    is_streaming = payload.get("stream", False)

    if is_streaming:
        return await _handle_streaming(payload, headers)
    else:
        resp = await http_client.post(
            f"{UPSTREAM}/v1/messages",
            content=json.dumps(payload),
            headers=headers,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=_safe_response_headers(resp.headers),
        )


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def passthrough(request: Request, path: str):
    body = await request.body()
    headers = _upstream_headers(request)
    resp = await http_client.request(
        method=request.method,
        url=f"{UPSTREAM}/{path}",
        content=body,
        headers=headers,
        params=dict(request.query_params),
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=_safe_response_headers(resp.headers),
    )


def _upstream_headers(request: Request) -> dict:
    skip = {"host", "content-length", "transfer-encoding"}
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in skip
    }
    if ANTHROPIC_API_KEY:
        headers["x-api-key"] = ANTHROPIC_API_KEY
    headers["content-type"] = "application/json"
    return headers


def _safe_response_headers(headers: httpx.Headers) -> dict:
    return {
        k: v for k, v in headers.items()
        if k.lower() not in _STRIP_RESPONSE_HEADERS
    }


async def _handle_streaming(payload: dict, headers: dict) -> Response:
    """Start a streaming request and return the right response type based on upstream status."""
    resp = await http_client.send(
        http_client.build_request(
            "POST",
            f"{UPSTREAM}/v1/messages",
            content=json.dumps(payload),
            headers=headers,
        ),
        stream=True,
    )

    # If upstream returned an error, read the body and return it directly
    if resp.status_code >= 400:
        body = await resp.aread()
        await resp.aclose()
        return Response(
            content=body,
            status_code=resp.status_code,
            headers=_safe_response_headers(resp.headers),
        )

    async def stream_body():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "text/event-stream"),
        headers=_safe_response_headers(resp.headers),
    )
