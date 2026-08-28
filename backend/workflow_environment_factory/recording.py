from __future__ import annotations

from typing import Any
from uuid import UUID

from .models import RecordingEvent, RecordingRecord, utc_now
from .store import FactoryStore


class RecordingService:
    def __init__(self, store: FactoryStore):
        self.store = store

    def start(self, name: str) -> RecordingRecord:
        return self.store.save_recording(RecordingRecord(name=name))

    def append(self, recording_id: UUID | str, event: RecordingEvent) -> RecordingRecord:
        recording = self._get(recording_id)
        if recording.status != "recording":
            raise ValueError("recording is already completed")
        recording.events.append(event)
        return self.store.save_recording(recording)

    def complete(self, recording_id: UUID | str, *, confirmed: bool) -> RecordingRecord:
        recording = self._get(recording_id)
        required = {"issue_read", "repository_changed", "pr_created", "issue_status_updated"}
        observed = {event.event_type for event in recording.events}
        if not required.issubset(observed):
            raise ValueError(f"recording is missing required events: {sorted(required - observed)}")
        if not confirmed:
            raise ValueError("recorded workflow variables and completion state must be confirmed by the user")
        recording.status = "completed"
        recording.confirmed = True
        recording.completed_at = utc_now()
        return self.store.save_recording(recording)

    def extract(self, recording_id: UUID | str) -> dict[str, Any]:
        recording = self._get(recording_id)
        latest: dict[str, dict[str, Any]] = {}
        for event in recording.events:
            latest[event.event_type] = event.data
        return {
            "recording_id": str(recording.recording_id),
            "status": recording.status,
            "confirmed": recording.confirmed,
            "candidate_variables": {
                "issue_key": latest.get("issue_read", {}).get("issue_key"),
                "target_status": latest.get("issue_status_updated", {}).get("status"),
                "pr_target": latest.get("pr_created", {}).get("target"),
                "branch": latest.get("pr_created", {}).get("branch"),
            },
            "completion_signals": [
                "repository verifier passes",
                "linked pull request exists",
                "pull request target matches",
                "issue reaches the recorded target status",
            ],
            "event_count": len(recording.events),
        }

    def _get(self, recording_id: UUID | str) -> RecordingRecord:
        recording = self.store.get_recording(recording_id)
        if recording is None:
            raise KeyError("recording not found")
        return recording
