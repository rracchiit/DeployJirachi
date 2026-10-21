"""Apps and deployments API.

The pipeline here is SIMULATED (timed sleeps and fake logs). The state machine,
validation, conflict handling and API shape are real. In Phase 4 the body of
`run_pipeline` is replaced by a real clone, docker build and docker run.
"""

import asyncio
import random
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/api/v1/apps", tags=["apps"])

REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

APPS: dict[int, dict] = {}
_next_id = 1
_tasks: set[asyncio.Task] = set()  # keep references so tasks are not garbage collected


class DeployRequest(BaseModel):
    url: str
    branch: str = "main"

    @field_validator("url")
    @classmethod
    def valid_url(cls, v: str) -> str:
        v = v.strip()
        if not REPO_RE.match(v):
            raise ValueError("URL must look like https://github.com/owner/repo")
        return v

    @field_validator("branch")
    @classmethod
    def valid_branch(cls, v: str) -> str:
        v = v.strip()
        if not BRANCH_RE.match(v) or ".." in v:
            raise ValueError("Branch name has invalid characters")
        return v


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _get(app_id: int) -> dict:
    app = APPS.get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


def _start_deployment(app: dict, branch: str) -> None:
    """Create a deployment row and launch the pipeline. No await between the
    busy check and setting busy, so two requests cannot both start a deploy."""
    if app["busy"]:
        raise HTTPException(status_code=409, detail="A deployment is already running for this app")
    d = {
        "n": len(app["deployments"]) + 1,
        "commit": secrets.token_hex(4)[:7],
        "branch": branch,
        "state": "QUEUED",
        "build": [],
        "runtime": [],
        "created": _now(),
    }
    app["deployments"].insert(0, d)
    app["busy"] = True
    app["status"] = "QUEUED"
    task = asyncio.create_task(run_pipeline(app, d))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_pipeline(app: dict, d: dict) -> None:
    def state(s: str) -> None:
        d["state"] = s
        app["status"] = s

    def log(m: str, c: str = "") -> None:
        d["build"].append({"m": m, "c": c})

    try:
        await asyncio.sleep(0.6)
        state("BUILDING")
        log(f"$ git clone --depth 1 --branch {d['branch']} github.com/{app['owner']}/{app['repo']}")
        await asyncio.sleep(0.9)
        log(f"Checked out {d['commit']}")
        for step in (
            "Step 1/5 : FROM python:3.12-slim",
            "Step 2/5 : WORKDIR /app",
            "Step 3/5 : COPY requirements.txt . && pip install -r requirements.txt",
        ):
            await asyncio.sleep(0.7)
            log(step)
        if "broken" in app["repo"].lower():
            await asyncio.sleep(0.9)
            log("Step 4/5 : RUN pip install not-a-real-package==9.9.9")
            log("ERROR: No matching distribution found for not-a-real-package==9.9.9", "l-err")
            await asyncio.sleep(0.5)
            log("Build failed: exit code 1", "l-err")
            state("FAILED")
            return
        await asyncio.sleep(0.8)
        log("Step 4/5 : COPY . .")
        await asyncio.sleep(0.6)
        log('Step 5/5 : CMD ["python","app.py"]')
        await asyncio.sleep(0.5)
        log(f"Successfully tagged cloudforge/{app['slug']}:{d['commit']}", "l-ok")
        state("STARTING")
        d["runtime"].append({"m": f"{_now()} container started (cpu=0.5, mem=256m)"})
        await asyncio.sleep(1.1)
        d["runtime"] += [{"m": f"{_now()} GET /health 200"}, {"m": f"{_now()} listening on :8000"}]
        log("Health check passed", "l-ok")
        app["startedAt"] = int(datetime.now().timestamp() * 1000)
        state("HEALTHY")
    except Exception as exc:  # never leave an app stuck in a "running" state
        log(f"Internal error: {exc}", "l-err")
        state("FAILED")
    finally:
        app["busy"] = False


def _sample_metrics(app: dict) -> None:
    """Simulated CPU and memory samples, one per GET while healthy."""
    if app["status"] == "HEALTHY":
        app["cpu"] = (app["cpu"] + [3 + random.random() * 12])[-30:]
        app["mem"] = (app["mem"] + [60 + random.random() * 30])[-30:]


@router.get("")
def list_apps() -> list[dict]:
    for a in APPS.values():
        _sample_metrics(a)
    return list(reversed(APPS.values()))


@router.post("", status_code=202)
async def create_or_deploy(body: DeployRequest) -> dict:
    global _next_id
    m = REPO_RE.match(body.url)
    owner, repo = m.group(1), m.group(2)
    app = next((a for a in APPS.values() if a["owner"] == owner and a["repo"] == repo), None)
    if app is None:
        slug = re.sub(r"[^a-z0-9-]", "-", f"{repo}-{secrets.token_hex(2)}".lower())
        app = {
            "id": _next_id, "owner": owner, "repo": repo, "slug": slug, "status": "NONE",
            "busy": False, "startedAt": None, "cpu": [], "mem": [], "deployments": [],
        }
        APPS[_next_id] = app
        _next_id += 1
    _start_deployment(app, body.branch)
    return app


@router.post("/{app_id}/redeploy", status_code=202)
async def redeploy(app_id: int) -> dict:
    app = _get(app_id)
    branch = app["deployments"][0]["branch"] if app["deployments"] else "main"
    _start_deployment(app, branch)
    return app


@router.post("/{app_id}/restart")
async def restart(app_id: int) -> dict:
    app = _get(app_id)
    if app["status"] != "HEALTHY":
        raise HTTPException(status_code=409, detail="Only a healthy app can be restarted")
    app["status"] = "STARTING"
    app["deployments"][0]["runtime"].append({"m": f"{_now()} container restarted"})

    async def finish() -> None:
        await asyncio.sleep(1.0)
        app["status"] = "HEALTHY"
        app["startedAt"] = int(datetime.now().timestamp() * 1000)

    task = asyncio.create_task(finish())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return app


@router.post("/{app_id}/stop")
async def stop(app_id: int) -> dict:
    app = _get(app_id)
    if app["status"] != "HEALTHY":
        raise HTTPException(status_code=409, detail="Only a healthy app can be stopped")
    app["status"] = "STOPPED"
    app["startedAt"] = None
    app["deployments"][0]["runtime"].append({"m": f"{_now()} container stopped"})
    return app


@router.delete("/{app_id}", status_code=204)
async def delete(app_id: int) -> Response:
    app = _get(app_id)
    if app["busy"]:
        raise HTTPException(status_code=409, detail="Cannot delete while a deployment is running")
    del APPS[app_id]
    return Response(status_code=204)
