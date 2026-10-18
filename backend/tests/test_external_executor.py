import asyncio
import json

import httpx
import pytest

from app.core.config import ExternalExecutorSettings
from app.executors.client import execute_external_function
from app.functions import FunctionExecutionError
from app.schemas.records import CreateRecordRequest, ExternalFunctionSpec


def _executor() -> ExternalExecutorSettings:
    return ExternalExecutorSettings(
        executor_id="research-policy-runner",
        base_url="https://executor.example.test",
        authorization_token="service-token",
        timeout_ms=5000,
    )


def test_external_function_spec_is_a_reference_not_an_endpoint() -> None:
    request = CreateRecordRequest.model_validate(
        {
            "table_name": "research_rules",
            "input": {"paper_level": "A"},
            "function": {
                "kind": "external",
                "executor_id": "research-policy-runner",
                "name": "calculate_paper_performance",
                "version": "2.1.0",
            },
        }
    )

    assert isinstance(request.function, ExternalFunctionSpec)
    assert request.function.executor_id == "research-policy-runner"


def test_external_executor_success_uses_controlled_url_and_auth() -> None:
    async def verify() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://executor.example.test/v1/executions"
            assert request.headers["Authorization"] == "Bearer service-token"
            assert request.headers["X-Execution-Id"] == "execution-1"
            assert json.loads(request.content) == {
                "execution_id": "execution-1",
                "record_id": "record-1",
                "table_name": "research_rules",
                "function": {
                    "name": "calculate_paper_performance",
                    "version": "2.1.0",
                },
                "input": {"paper_level": "A"},
                "timeout_ms": 5000,
            }
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "output": {"metric": "research_performance", "amount": 12000},
                },
            )

        output = await execute_external_function(
            executor_id="research-policy-runner",
            execution_id="execution-1",
            record_id="record-1",
            table_name="research_rules",
            function={"name": "calculate_paper_performance", "version": "2.1.0"},
            input_data={"paper_level": "A"},
            executor=_executor(),
            transport=httpx.MockTransport(handler),
        )
        assert output == {"metric": "research_performance", "amount": 12000}

    asyncio.run(verify())


def test_external_executor_converts_business_failure_and_bad_response() -> None:
    async def verify() -> None:
        async def business_failure(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "status": "failed",
                    "error": {
                        "code": "INVALID_AUTHOR_RANK",
                        "message": "author rank is invalid",
                        "details": {"author_rank": 4},
                    },
                },
            )

        with pytest.raises(FunctionExecutionError) as failed:
            await execute_external_function(
                executor_id="research-policy-runner",
                execution_id="execution-2",
                record_id="record-2",
                table_name="research_rules",
                function={"name": "calculate_paper_performance", "version": "2.1.0"},
                input_data={},
                executor=_executor(),
                transport=httpx.MockTransport(business_failure),
            )
        assert failed.value.code == "INVALID_AUTHOR_RANK"

        async def invalid_response(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "success", "output": []})

        with pytest.raises(FunctionExecutionError) as invalid:
            await execute_external_function(
                executor_id="research-policy-runner",
                execution_id="execution-3",
                record_id="record-3",
                table_name="research_rules",
                function={"name": "calculate_paper_performance", "version": "2.1.0"},
                input_data={},
                executor=_executor(),
                transport=httpx.MockTransport(invalid_response),
            )
        assert invalid.value.code == "EXECUTOR_INVALID_RESPONSE"

    asyncio.run(verify())


def test_external_executor_converts_timeout_and_auth_failure() -> None:
    async def verify() -> None:
        async def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with pytest.raises(FunctionExecutionError) as timed_out:
            await execute_external_function(
                executor_id="research-policy-runner",
                execution_id="execution-4",
                record_id="record-4",
                table_name="research_rules",
                function={"name": "calculate_paper_performance", "version": "2.1.0"},
                input_data={},
                executor=_executor(),
                transport=httpx.MockTransport(timeout),
            )
        assert timed_out.value.code == "EXECUTOR_TIMEOUT"

        async def unauthorized(_: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        with pytest.raises(FunctionExecutionError) as auth_failed:
            await execute_external_function(
                executor_id="research-policy-runner",
                execution_id="execution-5",
                record_id="record-5",
                table_name="research_rules",
                function={"name": "calculate_paper_performance", "version": "2.1.0"},
                input_data={},
                executor=_executor(),
                transport=httpx.MockTransport(unauthorized),
            )
        assert auth_failed.value.code == "EXECUTOR_AUTH_FAILED"

    asyncio.run(verify())
