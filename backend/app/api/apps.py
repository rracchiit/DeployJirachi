
import asyncio
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/api/v1/apps", tags=["apps"])

REPO_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

APPS = {}
next_id = 1


class DeployRequest(BaseModel):
    url: str
    branch: str = "main"

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        value = value.strip()
        if not REPO_RE.fullmatch(value):
            raise ValueError("Enter a valid GitHub repository URL")
        return value

    @field_validator("branch")
    @classmethod
    def valid_branch(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", value) or ".." in value:
            raise ValueError("Invalid branch name")
        return value


@router.get("")
def list_apps():
    return list(APPS.values())


@router.post("", status_code=202)
async def create_app(body: DeployRequest):
    global next_id

    match = REPO_RE.fullmatch(body.url.strip())
    owner, repo = match.group(1), match.group(2)

    for app in APPS.values():
        if app["owner"] == owner and app["repo"] == repo:
            raise HTTPException(
                status_code=409,
                detail="This repository is already registered",
            )

    app = {
        "id": next_id,
        "owner": owner,
        "repo": repo,
        "branch": body.branch,
        "status": "QUEUED",
        "created_at": datetime.now().isoformat(),
        "deployment_id": secrets.token_hex(4),
    }

    APPS[next_id] = app
    next_id += 1

    return app


@router.get("/{app_id}")
def get_app(app_id: int):
    app = APPS.get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="App not found")
    return app
