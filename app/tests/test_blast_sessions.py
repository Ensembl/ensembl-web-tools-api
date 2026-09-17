"""Exercise real session cleanup without calling the external BLAST service."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from aiohttp import ClientSession, ClientConnectionError, ClientPayloadError
from fastapi import Response
import pytest

from blast import blast


@pytest.fixture
def sessions(monkeypatch):
    created = []

    def create_session(**kwargs):
        session = ClientSession(**kwargs)
        created.append((session, session.connector))
        return session

    monkeypatch.setattr(blast, "ClientSession", create_session)
    return created


def stub_upstream(monkeypatch, status=200, content="FINISHED", failure=None):
    @asynccontextmanager
    async def request(self, *args, **kwargs):
        if failure == "connect":
            raise ClientConnectionError("upstream unavailable")
        response = AsyncMock(status=status)
        response.text.return_value = content
        if failure == "read":
            response.text.side_effect = ClientPayloadError("incomplete response")
        elif failure == "cancel":
            response.text.side_effect = asyncio.CancelledError()
        # Yield to other requests to exercise concurrent session ownership.
        await asyncio.sleep(0)
        yield response

    monkeypatch.setattr(ClientSession, "get", request)
    monkeypatch.setattr(ClientSession, "post", request)


async def call_blast(operation):
    if operation == "submit":
        return await blast.run_blast(
            {"id": 1, "value": "ATGC"}, {}, "genome-id", "dna"
        )
    return await blast.blast_proxy("result", "job-id/json", Response())


async def assert_closed(sessions):
    try:
        assert sessions
        assert all(session.closed for session, _ in sessions)
        assert all(connector.closed for _, connector in sessions)
    finally:
        # Keep a regression failure from leaking resources in the test runner.
        for session, _ in sessions:
            await session.close()


@pytest.mark.parametrize("operation", ["submit", "proxy"])
@pytest.mark.parametrize("status", [200, 400, 404, 500])
def test_sessions_close_after_response(monkeypatch, sessions, operation, status):
    stub_upstream(monkeypatch, status=status, content="upstream response")

    async def exercise():
        result = await call_blast(operation)
        await assert_closed(sessions)
        assert ("error" in result) == (status != 200)

    asyncio.run(exercise())


@pytest.mark.parametrize("operation", ["submit", "proxy"])
@pytest.mark.parametrize(
    "failure, exception",
    [
        ("connect", ClientConnectionError),
        ("read", ClientPayloadError),
        ("cancel", asyncio.CancelledError),
    ],
)
def test_sessions_close_after_exception(
    monkeypatch, sessions, operation, failure, exception
):
    stub_upstream(monkeypatch, failure=failure)

    async def exercise():
        with pytest.raises(exception):
            await call_blast(operation)
        await assert_closed(sessions)

    asyncio.run(exercise())


def test_concurrent_status_requests_close_all_sessions(monkeypatch, sessions):
    stub_upstream(monkeypatch, content="NOT_FOUND")

    async def exercise():
        result = await blast.blast_job_statuses(
            blast.JobIDs(job_ids=["job-1", "job-2", "job-3"])
        )
        await assert_closed(sessions)
        assert result == {
            "statuses": [
                {"job_id": job_id, "status": "NOT_FOUND"}
                for job_id in ["job-1", "job-2", "job-3"]
            ]
        }

    asyncio.run(exercise())


def test_not_found_status_does_not_require_response(monkeypatch, sessions):
    stub_upstream(monkeypatch, status=400, content="<p>Job not found</p>")

    async def exercise():
        try:
            result = await blast.get_blast_job_status("missing-job")
        finally:
            await assert_closed(sessions)
        assert result == {"error": "Job not found", "job_id": "missing-job"}

    asyncio.run(exercise())


def test_proxy_preserves_not_found_http_status(monkeypatch, sessions):
    stub_upstream(monkeypatch, status=400, content="<p>Job not found</p>")

    async def exercise():
        response = Response()
        result = await blast.blast_proxy("result", "missing-job", response)
        await assert_closed(sessions)
        assert response.status_code == 404
        assert result == {"error": "Job not found"}

    asyncio.run(exercise())
