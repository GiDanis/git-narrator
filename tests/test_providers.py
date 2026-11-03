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
from git_narrator.schemas import GitNarratorReport, RiskCategory
from git_narrator.transport import HTTPStatusError

MOCK_REPORT = {
    "executive_summary": {
        "headline": "Refactor database connection pool",
        "intent": "Enhance connection recycling under peak load",
        "overall_impact": "Prevents socket exhaustion",
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
    """Test Ollama payload construction and streaming NDJSON parsing."""
    captured_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "qwen2.5-coder"
        assert body["stream"] is True
        assert "format" in body

        # Stream 2 chunks then done
        report_json = json.dumps(MOCK_REPORT)
        half = len(report_json) // 2
        part1 = json.dumps({"message": {"content": report_json[:half]}, "done": False})
        part2 = json.dumps({"message": {"content": report_json[half:]}, "done": True})
        content = f"{part1}\n{part2}\n".encode()
        return httpx.Response(200, content=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = OllamaProvider(model="qwen2.5-coder", client=client)

    chunks = []
    async for chunk in provider.stream_structured("System instructions", "User diff"):
        chunks.append(chunk)

    assert len(chunks) == 2
    full_output = "".join(chunks)
    parsed = json.loads(full_output)
    assert parsed["conventional_commit"].startswith("refactor(db):")

    report = await provider.generate_report("System instructions", "User diff")
    assert isinstance(report, GitNarratorReport)
    assert report.conventional_commit == "refactor(db): implement dynamic pool connection recycling"
    assert report.risk_radar[0].category == RiskCategory.CONCURRENCY_RACE

    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_provider_stream_and_payload():
    """Test Gemini payload construction, schema cleaning, and SSE streaming."""
    captured_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        assert "x-goog-api-key" in request.headers
        assert request.headers["x-goog-api-key"] == "test-gemini-key"
        assert "alt=sse" in str(request.url)

        body = json.loads(request.content.decode("utf-8"))
        assert "generationConfig" in body
        gen_cfg = body["generationConfig"]
        assert gen_cfg["response_mime_type"] == "application/json"
        assert "$defs" not in gen_cfg["response_schema"]

        report_json = json.dumps(MOCK_REPORT)
        sse_body = (
            f'data: {{"candidates": [{{"content": {{"parts": [{{"text": {json.dumps(report_json)}}}]}}}}]}}\n\n'
        ).encode()
        return httpx.Response(200, content=sse_body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = GeminiProvider(
        model="gemini-2.0-flash",
        api_key="test-gemini-key",
        client=client,
    )

    chunks = []
    async for chunk in provider.stream_structured("System", "Diff"):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert "Refactor database connection pool" in chunks[0]

    report = await provider.generate_report("System", "Diff")
    assert isinstance(report, GitNarratorReport)
    assert report.executive_summary.headline == "Refactor database connection pool"

    await client.aclose()


@pytest.mark.asyncio
async def test_openai_provider_stream_and_payload():
    """Test OpenAI-compatible provider payload, strict json_schema, and SSE stream."""
    captured_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-openai-key"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "gpt-4o"
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True

        report_json = json.dumps(MOCK_REPORT)
        chunk1 = json.dumps({"choices": [{"delta": {"content": report_json[:50]}}]})
        chunk2 = json.dumps({"choices": [{"delta": {"content": report_json[50:]}}]})
        sse_body = f"data: {chunk1}\n\ndata: {chunk2}\n\ndata: [DONE]\n\n".encode()
        return httpx.Response(200, content=sse_body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = OpenAIProvider(
        model="gpt-4o",
        api_key="test-openai-key",
        client=client,
    )

    chunks = []
    async for chunk in provider.stream_structured("System", "Diff"):
        chunks.append(chunk)

    assert len(chunks) == 2
    full = "".join(chunks)
    assert json.loads(full)["conventional_commit"] == "refactor(db): implement dynamic pool connection recycling"

    report = await provider.generate_report("System", "Diff")
    assert isinstance(report, GitNarratorReport)
    await client.aclose()


@pytest.mark.asyncio
async def test_anthropic_provider_stream_and_payload():
    """Test Anthropic tool-use payload, tool_choice, and input_json_delta streaming."""
    captured_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        assert request.headers["x-api-key"] == "test-anthropic-key"
        assert request.headers["anthropic-version"] == "2023-06-01"

        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "claude-3-5-sonnet-20241022"
        assert body["tool_choice"]["type"] == "tool"
        assert body["tools"][0]["name"] == "emit_git_narrator_report"

        report_json = json.dumps(MOCK_REPORT)
        delta_event = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {
                "type": "input_json_delta",
                "partial_json": report_json,
            },
        }
        sse_body = f"data: {json.dumps(delta_event)}\n\n".encode()
        return httpx.Response(200, content=sse_body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = AnthropicProvider(
        api_key="test-anthropic-key",
        client=client,
    )

    chunks = []
    async for chunk in provider.stream_structured("System", "Diff"):
        chunks.append(chunk)

    assert len(chunks) == 1
    report = await provider.generate_report("System", "Diff")
    assert isinstance(report, GitNarratorReport)
    assert report.executive_summary.intent == "Enhance connection recycling under peak load"

    await client.aclose()


@pytest.mark.asyncio
async def test_provider_error_handling():
    """Test that HTTP errors from provider raise HTTPStatusError with body details."""
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
    """Test create_provider factory for all supported aliases."""
    ollama = create_provider("ollama")
    assert isinstance(ollama, OllamaProvider)
    assert ollama.model == "llama3.2"

    gemini = create_provider("gemini", api_key="abc")
    assert isinstance(gemini, GeminiProvider)
    assert gemini.model == "gemini-1.5-flash"

    openai = create_provider("openai", api_key="abc")
    assert isinstance(openai, OpenAIProvider)
    assert openai.model == "gpt-4o"

    groq = create_provider("groq", api_key="abc")
    assert isinstance(groq, OpenAIProvider)
    assert "groq.com" in groq.base_url

    deepseek = create_provider("deepseek", api_key="abc")
    assert isinstance(deepseek, OpenAIProvider)
    assert "deepseek.com" in deepseek.base_url

    anthropic = create_provider("anthropic", api_key="abc")
    assert isinstance(anthropic, AnthropicProvider)
    assert "claude" in anthropic.model

    with pytest.raises(ValueError):
        create_provider("unsupported_provider")
