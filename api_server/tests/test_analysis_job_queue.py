from __future__ import annotations

import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.schemas.account import AuthenticatedUser
from app.integrations import redis_cache
from app.services import analysis_job_service as jobs


class AnalysisJobQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.originals = {
            "get_settings": jobs.get_settings,
            "persist_snapshot": jobs._persist_job_snapshot,
            "run_analysis": jobs.run_smart_cv_analysis,
            "ping": jobs.redis_cache.ping,
            "get_json": jobs.redis_cache.get_json,
            "set_json": jobs.redis_cache.set_json,
            "stream_add": jobs.redis_cache.stream_add,
            "acquire_slot": jobs.redis_cache.acquire_slot,
            "release_slot": jobs.redis_cache.release_slot,
        }
        self.settings = SimpleNamespace(
            analysis_job_mode="redis",
            analysis_job_queue_key="test:analysis:queue",
            analysis_job_consumer_group="test-workers",
            analysis_job_reclaim_idle_seconds=60,
            analysis_job_stream_max_length=1000,
            analysis_job_result_ttl_seconds=600,
            analysis_job_lease_seconds=300,
            analysis_job_max_concurrency_per_user=3,
        )
        self.redis_store: dict[str, object] = {}
        self.queue: list[object] = []
        self.released: list[tuple[str, str]] = []

        jobs.get_settings = lambda: self.settings  # type: ignore[assignment]
        jobs._persist_job_snapshot = lambda _record: None  # type: ignore[assignment]
        jobs.redis_cache.ping = lambda: True  # type: ignore[assignment]
        jobs.redis_cache.get_json = lambda key: copy.deepcopy(self.redis_store.get(key))  # type: ignore[assignment]

        def set_json(key: str, payload: object, _ttl: int) -> bool:
            self.redis_store[key] = copy.deepcopy(payload)
            return True

        jobs.redis_cache.set_json = set_json  # type: ignore[assignment]
        def stream_add(_key: str, payload: object, _max_length: int) -> str:
            self.queue.append(copy.deepcopy(payload))
            return "1-0"

        jobs.redis_cache.stream_add = stream_add  # type: ignore[assignment]
        jobs.redis_cache.acquire_slot = lambda *_args, **_kwargs: True  # type: ignore[assignment]

        def release_slot(key: str, token: str) -> bool:
            self.released.append((key, token))
            return True

        jobs.redis_cache.release_slot = release_slot  # type: ignore[assignment]
        jobs._jobs.clear()

    def tearDown(self) -> None:
        jobs.get_settings = self.originals["get_settings"]  # type: ignore[assignment]
        jobs._persist_job_snapshot = self.originals["persist_snapshot"]  # type: ignore[assignment]
        jobs.run_smart_cv_analysis = self.originals["run_analysis"]  # type: ignore[assignment]
        jobs.redis_cache.ping = self.originals["ping"]  # type: ignore[assignment]
        jobs.redis_cache.get_json = self.originals["get_json"]  # type: ignore[assignment]
        jobs.redis_cache.set_json = self.originals["set_json"]  # type: ignore[assignment]
        jobs.redis_cache.stream_add = self.originals["stream_add"]  # type: ignore[assignment]
        jobs.redis_cache.acquire_slot = self.originals["acquire_slot"]  # type: ignore[assignment]
        jobs.redis_cache.release_slot = self.originals["release_slot"]  # type: ignore[assignment]
        jobs._jobs.clear()

    def _payload(self) -> dict[str, object]:
        return {
            "jd_text": "Python backend engineer",
            "weights": {},
            "hard_filters": {},
            "cv_entries": [{"file_name": "candidate.pdf", "text": "Python FastAPI"}],
        }

    def test_redis_mode_persists_and_enqueues_job(self) -> None:
        user = AuthenticatedUser(uid="user-1", email="hr@example.com")

        job = jobs.start_analysis_job(self._payload(), current_user=user)

        self.assertEqual(job["status"], "queued")
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(self.queue[0]["job_id"], job["job_id"])
        cached = self.redis_store[f"supporthr:analysis:job:{job['job_id']}"]
        self.assertEqual(cached["execution_mode"], "redis")
        self.assertIsInstance(cached["payload"], dict)

    def test_worker_completes_shared_job_and_releases_slot(self) -> None:
        user = AuthenticatedUser(uid="user-2", email="hr@example.com")
        job = jobs.start_analysis_job(self._payload(), current_user=user)

        async def fake_analysis(*_args, **_kwargs):
            return {"candidates": [{"candidateName": "A"}], "pipeline": {"source": "test"}}

        jobs.run_smart_cv_analysis = fake_analysis  # type: ignore[assignment]
        jobs._jobs.clear()  # Force the worker path to reload state from Redis.

        completed = asyncio.run(jobs.execute_queued_analysis_job(str(job["job_id"])))

        self.assertTrue(completed)
        current = self.redis_store[f"supporthr:analysis:job:{job['job_id']}"]
        self.assertEqual(current["status"], "completed")
        self.assertIsNone(current["payload"])
        self.assertEqual(current["result"]["candidates"][0]["candidateName"], "A")
        self.assertEqual(self.released[-1][1], job["job_id"])

    def test_vector_rebuild_uses_same_durable_queue_and_worker_status(self) -> None:
        user = AuthenticatedUser(uid="user-vector", email="hr@example.com")
        job = jobs.start_vector_rebuild_job(user, limit_count=25)
        cached = self.redis_store[f"supporthr:analysis:job:{job['job_id']}"]
        self.assertEqual(cached["job_type"], "vector_rebuild")
        self.assertEqual(cached["payload"], {"limit_count": 25})
        jobs._jobs.clear()

        with patch(
            "app.services.vector_index_service.rebuild_uploaded_file_vector_index",
            return_value={"processed": 2, "indexed": 2, "skipped": 0, "failed": 0, "entries": []},
        ):
            completed = asyncio.run(jobs.execute_queued_analysis_job(str(job["job_id"])))

        self.assertTrue(completed)
        current = self.redis_store[f"supporthr:analysis:job:{job['job_id']}"]
        self.assertEqual(current["status"], "completed")
        self.assertEqual(current["result"]["indexed"], 2)
        self.assertEqual(self.released[-1][1], job["job_id"])

    def test_required_redis_mode_rejects_when_queue_is_down(self) -> None:
        jobs.redis_cache.ping = lambda: False  # type: ignore[assignment]

        with self.assertRaises(HTTPException) as raised:
            jobs.start_analysis_job(self._payload())

        self.assertEqual(raised.exception.status_code, 503)

    def test_malformed_stream_payload_keeps_message_id_for_ack(self) -> None:
        decoded = redis_cache._decode_stream_message(("9-1", {"payload": "not-json"}))

        self.assertEqual(decoded, ("9-1", None))


if __name__ == "__main__":
    unittest.main()
