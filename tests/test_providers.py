"""Unit tests for git_narrator LLM providers with mock HTTP transports."""

import json

import httpx
import pytest

from git_narrator.providers import (
    AnthropicProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    create_provider,
)
from git_narrator.providers.ollama import select_best_ollama_model
from git_narrator.schemas import GitNarratorReport, RiskCategory
from git_narrator.transport import HTTPStatusError, TransportError

MOCK_REPORT = {
    "executive_summary": {
        "headline": "Refactor database connection pool",
        "intent": "Enhance connection recycling under peak load",
        "overall_impact": "Prevents socket exhaustion",
        "blast_radius": "MEDIUM",
        "tags": ["database", "perf"],
    },
    "architecture_narrative": {
        "before_state": "Single shared pool without max_overflow",
        "after_state": "Dynamic pool with health checks and timeout fallback",
        "tech_debt": "None",
        "components_affected": [
            {
                "component_name": "DBPool",
                "mutation_type": "REFACTORED",
                "summary": "Added connection reaping and pool metrics",
            }
        ],
    },
    "risk_radar": [
        {
            "category": "CONCURRENCY_RACE",
            "severity": "MEDIUM",
            "title": "Pool resize during transaction checkout",
            "file_path": "db/pool.py",
            "line_hint": "L88",
            "explanation": "Lock must be held while acquiring connections.",
            "remediation": "Acquire pool._mutex before evaluating capacity.",
        }
    ],
    "visual_flow": {
        "diagram_type": "flowchart",
        "mermaid_code": 'graph LR\nA["Client"] --> B["DBPool"]\nB --> C["Postgres"]',
        "ascii_diagram": "[Client] -> [DBPool] -> [Postgres]",
    },
    "review_checklist": {
        "manual_checks": ["Run load test with 200 concurrent workers"],
        "breaking_changes": [],
    },
    "conventional_commit": "refactor(db): implement dynamic pool connection recycling",
}


@pytest.mark.asyncio
async def test_ollama_provider_stream_and_payload():
    """Test Ollama payload construction, options num_ctx, and streaming NDJSON parsing."""
    captured_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "qwen2.5-coder"
        assert body["stream"] is True
        assert body["options"]["num_ctx"] == 16384
        assert "format" in body

        report_json = json.dumps(MOCK_REPORT)
        half = len(report_json) // 2
        part1 = json.dumps({"message": {"content": report_json[:half]}, "done": False})
        part2 = json.dumps({"message": {"content": report_json[half:]}, "done": True})
        return httpx.Response(200, content=f"{part1}\n{part2}\n".encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = OllamaProvider(model="qwen2.5-coder", client=client)

    chunks = [c async for c in provider.stream_structured("System instructions", "User diff")]
    assert len(chunks) == 2
    assert json.loads("".join(chunks))["conventional_commit"].startswith("refactor(db):")

    report = await provider.generate_report("System instructions", "User diff")
    assert isinstance(report, GitNarratorReport)
    assert report.risk_radar[0].category == RiskCategory.CONCURRENCY_RACE
    await client.aclose()


def test_ollama_model_auto_selection():
    assert select_best_ollama_model(["llama3.2:latest", "qwen2.5-coder:7b"]) == "qwen2.5-coder:7b"
    assert select_best_ollama_model(["mistral:latest", "qwen3:8b"]) == "qwen3:8b"
    assert select_best_ollama_model(["custom-local:v1"]) == "custom-local:v1"
    assert select_best_ollama_model([], preferred="fallback-model") == "fallback-model"


@pytest.mark.asyncio
async def test_gemini_provider_stream_and_payload():
    """Test Gemini OpenAPI nullable schema cleaning and SSE streaming."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-gemini-key"
        assert "alt=sse" in str(request.url)

        body = json.loads(request.content.decode("utf-8"))
        gen_cfg = body["generationConfig"]
        assert gen_cfg["response_mime_type"] == "application/json"
        schema = gen_cfg["response_schema"]
        assert "$defs" not in schema
        assert "default" not in schema["properties"]["visual_flow"]
        assert schema["properties"]["visual_flow"]["nullable"] is True
        assert schema["properties"]["risk_radar"]["items"]["properties"]["file_path"]["nullable"] is True

        report_json = json.dumps(MOCK_REPORT)
        sse_body = (
            f'data: {{"candidates": [{{"content": {{"parts": [{{"text": {json.dumps(report_json)}}}]}}}}]}}\n\n'
        ).encode()
        return httpx.Response(200, content=sse_body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = GeminiProvider(model="gemini-2.5-flash", api_key="test-gemini-key", client=client)

    report = await provider.generate_report("System", "Diff")
    assert isinstance(report, GitNarratorReport)
    assert report.executive_summary.headline == "Refactor database connection pool"
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_safety_block_raises_transport_error():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'data: {"candidates": [{"finishReason": "SAFETY"}]}\n\n',
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = GeminiProvider(api_key="test-key", client=client)
    with pytest.raises(TransportError):
        async for _ in provider.stream_structured("Sys", "Diff"):
            pass
    await client.aclose()


@pytest.mark.asyncio
async def test_openai_provider_stream_and_strict_schema():
    """Test OpenAI payload enforces additionalProperties:false & complete required keys for strict mode."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-openai-key"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "gpt-4.1-mini"
        fmt = body["response_format"]
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["strict"] is True

        schema = fmt["json_schema"]["schema"]
        assert "$defs" not in schema
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"].keys())
        exec_node = schema["properties"]["executive_summary"]
        assert exec_node["additionalProperties"] is False
        assert set(exec_node["required"]) == set(exec_node["properties"].keys())

        report_json = json.dumps(MOCK_REPORT)
        chunk1 = json.dumps({"choices": [{"delta": {"content": report_json[:50]}}]})
        chunk2 = json.dumps({"choices": [{"delta": {"content": report_json[50:]}}]})
        return httpx.Response(200, content=f"data: {chunk1}\n\ndata: {chunk2}\n\ndata: [DONE]\n\n".encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = OpenAIProvider(model="gpt-4.1-mini", api_key="test-openai-key", client=client)

    report = await provider.generate_report("System", "Diff")
    assert isinstance(report, GitNarratorReport)
    assert report.conventional_commit == "refactor(db): implement dynamic pool connection recycling"
    await client.aclose()


@pytest.mark.asyncio
async def test_anthropic_provider_stream_and_payload():
    """Test Anthropic tool-use payload, tool_choice, and input_json_delta streaming."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "test-anthropic-key"
        assert request.headers["anthropic-version"] == "2023-06-01"

        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "claude-haiku-5-5"
        assert body["tool_choice"]["type"] == "tool"
        assert body["tools"][0]["name"] == "emit_git_narrator_report"

        delta_event = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": json.dumps(MOCK_REPORT)},
        }
        return httpx.Response(200, content=f"data: {json.dumps(delta_event)}\n\n".encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = AnthropicProvider(api_key="test-anthropic-key", client=client)

    report = await provider.generate_report("System", "Diff")
    assert isinstance(report, GitNarratorReport)
    assert report.executive_summary.intent == "Enhance connection recycling under peak load"
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_error_handling():
    """Test that HTTP errors from provider raise HTTPStatusError with concise body details."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API key"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = OpenAIProvider(api_key="bad-key", client=client)

    with pytest.raises(HTTPStatusError) as exc_info:
        async for _ in provider.stream_structured("System", "Diff"):
            pass

    assert exc_info.value.status_code == 401
    assert "Invalid API key" in exc_info.value.message
    await client.aclose()


def test_provider_factory():
    """Test create_provider factory across all supported providers & aliases."""
    ollama = create_provider("ollama")
    assert isinstance(ollama, OllamaProvider)
    assert ollama.model == "qwen2.5-coder:7b"

    gemini = create_provider("gemini", api_key="abc")
    assert isinstance(gemini, GeminiProvider)
    assert gemini.model == "gemini-2.5-flash"

    openai = create_provider("openai", api_key="abc")
    assert isinstance(openai, OpenAIProvider)
    assert openai.model == "gpt-4.1-mini"
    assert openai.supports_native_schema is True

    groq = create_provider("groq", api_key="abc")
    assert isinstance(groq, OpenAIProvider)
    assert "groq.com" in groq.base_url
    assert groq.use_json_object is True
    assert groq.supports_native_schema is False

    deepseek = create_provider("deepseek", api_key="abc")
    assert isinstance(deepseek, OpenAIProvider)
    assert "deepseek.com" in deepseek.base_url
    assert deepseek.use_json_object is True

    anthropic = create_provider("claude", api_key="abc")
    assert isinstance(anthropic, AnthropicProvider)
    assert "claude" in anthropic.model

    with pytest.raises(ValueError):
        create_provider("unsupported_provider")
