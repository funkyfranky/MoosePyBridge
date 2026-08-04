"""Append-only persistent audit records for daemon-owned command history."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Iterable

LOGGER = logging.getLogger(__name__)
AUDIT_SCHEMA_VERSION = 1


class AuditStore:
    """Small append-only JSONL store with an in-memory query index."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._records: list[dict[str, Any]] = []
        self._file = None
        self._load()

    def open(self) -> None:
        """Open the append stream when persistent storage is configured."""

        if self.path is None or self._file is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")

    def close(self) -> None:
        """Flush and close the persistent stream."""

        if self._file is not None:
            self._file.close()
            self._file = None

    def append(
        self,
        record_type: str,
        payload: dict[str, Any],
        *,
        client_identity: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Append one versioned record and return the stored envelope."""

        record_type = record_type.strip()
        if not record_type:
            raise ValueError("audit record_type must not be empty")
        record = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "record_type": record_type,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": payload,
        }
        if client_identity:
            record["client"] = dict(client_identity)
        json_line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self._records.append(record)
        if self.path is not None:
            self.open()
            assert self._file is not None
            self._file.write(json_line + "\n")
            self._file.flush()
        return record

    def query(
        self,
        *,
        record_type: str | None = None,
        plan_id: str | None = None,
        attempt_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return matching records in append order."""

        records: Iterable[dict[str, Any]] = self._records
        if record_type is not None:
            records = (record for record in records if record.get("record_type") == record_type)
        if plan_id is not None:
            records = (
                record
                for record in records
                if isinstance(record.get("payload"), dict) and record["payload"].get("plan_id") == plan_id
            )
        if attempt_id is not None:
            records = (
                record
                for record in records
                if isinstance(record.get("payload"), dict) and record["payload"].get("attempt_id") == attempt_id
            )
        return tuple(records)

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
                        raise ValueError("record and payload must be JSON objects")
                    if record.get("schema_version") != AUDIT_SCHEMA_VERSION:
                        raise ValueError(f"unsupported schema version {record.get('schema_version')!r}")
                    self._records.append(record)
                except (ValueError, json.JSONDecodeError) as exc:
                    LOGGER.warning("Ignoring invalid audit record %s:%s: %s", self.path, line_number, exc)


def latest_attempt_records(records: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Collapse execution snapshots to the latest record for each attempt id."""

    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        attempt_id = str(payload.get("attempt_id") or "")
        if attempt_id:
            latest[attempt_id] = record
    return tuple(
        sorted(
            latest.values(),
            key=lambda record: (
                int(record["payload"].get("attempt_number") or 0),
                str(record.get("recorded_at") or ""),
            ),
        )
    )


__all__ = ["AUDIT_SCHEMA_VERSION", "AuditStore", "latest_attempt_records"]
