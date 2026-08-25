import asyncio
import json

from app.vep import vep_resources


def test_submission_status_is_not_cacheable(monkeypatch):
    async def fake_get_workflow_status(submission_id):
        assert submission_id == "workflow-id"
        return {"workflow": {"status": "RUNNING"}}

    monkeypatch.setattr(
        vep_resources, "get_workflow_status", fake_get_workflow_status
    )

    response = asyncio.run(
        vep_resources.vep_status(request=None, submission_id="workflow-id")
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body) == {
        "submission_id": "workflow-id",
        "status": "RUNNING",
    }