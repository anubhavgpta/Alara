"""OpenHands coding backend — drives a local OpenHands server via its REST API."""

import json
import logging
from typing import Callable

import httpx

from alara.coding.base import CodingBackend
from alara.coding.models import CodingResult, CodingTask
from alara.core.errors import AlaraAPIError

logger = logging.getLogger(__name__)


class OpenHandsBackend(CodingBackend):
    """Coding backend that delegates to a locally running OpenHands server.

    Args:
        base_url:        Base URL of the OpenHands server, e.g. http://localhost:3000.
        timeout_seconds: HTTP timeout for all requests, including SSE polling.
    """

    def __init__(self, base_url: str, timeout_seconds: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def is_available(self) -> bool:
        """Return True if GET /health responds within 3 seconds."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code < 500
        except Exception as exc:
            logger.debug("OpenHands health check failed: %s", exc)
            return False

    async def run(
        self,
        task: CodingTask,
        on_chunk: Callable[[str], None],
    ) -> CodingResult:
        """Start an OpenHands conversation and stream events back via SSE.

        Steps:
          1. POST /api/conversations to start a session.
          2. Stream GET /api/conversations/{id}/events (SSE) and forward
             each event message to on_chunk.
          3. DELETE /api/conversations/{id} on completion or error.

        Returns:
            CodingResult.  Raises AlaraAPIError on any httpx failure.
        """
        initial_message = task.description
        if task.read_only:
            initial_message += " Do not modify any files."

        logger.info(
            "OpenHandsBackend.run: workdir=%s read_only=%s",
            task.workdir, task.read_only,
        )

        conv_id: str | None = None

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            ) as client:
                # --- Start conversation ---
                try:
                    create_resp = await client.post(
                        "/api/conversations",
                        json={
                            "initial_message": initial_message,
                            "repository": str(task.workdir),
                        },
                    )
                    create_resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise AlaraAPIError(
                        f"OpenHands failed to create conversation: {exc}"
                    ) from exc

                conv_id = create_resp.json().get("id") or create_resp.json().get("conversation_id")
                if not conv_id:
                    raise AlaraAPIError(
                        "OpenHands returned no conversation ID in POST /api/conversations response."
                    )
                logger.debug("OpenHands conversation started: %s", conv_id)

                # --- Stream events via SSE ---
                try:
                    async with client.stream(
                        "GET",
                        f"/api/conversations/{conv_id}/events",
                    ) as stream:
                        async for line in stream.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if not data_str:
                                continue
                            try:
                                event: dict = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            message = event.get("message") or event.get("content", "")
                            if message:
                                on_chunk(str(message))

                            event_type = str(event.get("type", "")).lower()
                            if event_type in ("finish", "done", "completed", "error"):
                                logger.debug(
                                    "OpenHands conversation finished: type=%s", event_type
                                )
                                break
                except httpx.HTTPError as exc:
                    raise AlaraAPIError(
                        f"OpenHands SSE stream error for conversation {conv_id}: {exc}"
                    ) from exc

                # --- Clean up ---
                try:
                    await client.delete(f"/api/conversations/{conv_id}")
                    logger.debug("OpenHands conversation deleted: %s", conv_id)
                except Exception as cleanup_exc:
                    logger.warning(
                        "Failed to delete OpenHands conversation %s: %s",
                        conv_id, cleanup_exc,
                    )

        except AlaraAPIError:
            raise
        except httpx.TimeoutException as exc:
            raise AlaraAPIError(
                f"OpenHands request timed out (timeout={self._timeout}s): {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AlaraAPIError(f"OpenHands HTTP error: {exc}") from exc

        return CodingResult(
            success=True,
            summary="",
            diff=None,
            shell_output=None,
            error=None,
        )
