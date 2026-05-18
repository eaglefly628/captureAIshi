"""Scripted batch render simulator.

Emits SSE events matching the production UE commandlet stdout protocol:
  PROGRESS pcg_start
  PROGRESS pcg_done elapsed=4.2
  PROGRESS mrq_frame N/M
  PROGRESS mrq_done elapsed=...
  DONE manifest=<path>

so the frontend code that ships for the demo is byte-equivalent to the
code that will ship against the real UE MCP / commandlet stack.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class JobState:
    job_id: str
    scene_id: str
    variant_id: str
    params: dict[str, Any]
    status: str = "queued"
    frame_index: int = 0
    frame_total: int = 30
    eta_ms: int = 0
    rationale: str = ""
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class DemoJobRegistry:
    def __init__(self):
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def submit(
        self, scene_id: str, params: dict[str, Any], rationale: str = ""
    ) -> JobState:
        with self._lock:
            existing = sum(
                1 for j in self._jobs.values() if j.scene_id == scene_id
            )
            variant_id = f"v0_{existing + 1}"
            jid = uuid.uuid4().hex[:8]
            st = JobState(
                job_id=jid,
                scene_id=scene_id,
                variant_id=variant_id,
                params=dict(params),
                rationale=rationale,
            )
            self._jobs[jid] = st
            return st

    def get(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobState]:
        with self._lock:
            return sorted(
                self._jobs.values(), key=lambda j: j.created_ms, reverse=True
            )

    def stream(self, job_id: str) -> Iterator[str]:
        job = self._jobs.get(job_id)
        if not job:
            yield _sse("error", {"message": f"unknown job {job_id}"})
            return

        job.status = "pcg"
        yield _sse("status", _state(job))
        yield _sse("log", {"line": "PROGRESS pcg_start"})
        for i in range(8):
            time.sleep(0.5)
            yield _sse("log", {
                "line": f"PROGRESS pcg_tick {i + 1}/8 instances={500 * (i + 1)}"
            })
        yield _sse("log", {"line": "PROGRESS pcg_done elapsed=4.2"})

        job.status = "mrq"
        yield _sse("status", _state(job))
        for f in range(1, job.frame_total + 1):
            time.sleep(0.6)
            job.frame_index = f
            yield _sse("log", {"line": f"PROGRESS mrq_frame {f}/{job.frame_total}"})
            if f % 5 == 0:
                yield _sse("frame", {
                    "job_id": job.job_id,
                    "scene_id": job.scene_id,
                    "variant_id": job.variant_id,
                    "frame_index": f,
                    "frame_total": job.frame_total,
                    "thumbnail_url": (
                        f"/api/demo/thumbnail/{job.scene_id}?"
                        f"frame={f}&variant={job.variant_id}"
                    ),
                })
            yield _sse("status", _state(job))

        yield _sse("log", {"line": "PROGRESS mrq_done elapsed=18.4"})
        manifest_path = (
            f"Saved/MovieRenders/{job.scene_id}/{job.variant_id}/manifest.json"
        )
        yield _sse("log", {"line": f"DONE manifest={manifest_path}"})

        job.status = "done"
        yield _sse("done", {
            "job_id": job.job_id,
            "scene_id": job.scene_id,
            "variant_id": job.variant_id,
            "manifest_path": manifest_path,
            "frames": job.frame_total,
            "channels": [
                "FinalImage", "WorldNormal", "SceneDepth",
                "ObjectId", "GBufferA",
            ],
            "thumbnail_url": (
                f"/api/demo/thumbnail/{job.scene_id}?"
                f"frame={job.frame_total}&variant={job.variant_id}"
            ),
        })


def _state(job: JobState) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "scene_id": job.scene_id,
        "variant_id": job.variant_id,
        "status": job.status,
        "frame_index": job.frame_index,
        "frame_total": job.frame_total,
    }


def _sse(event: str, data: dict[str, Any]) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
