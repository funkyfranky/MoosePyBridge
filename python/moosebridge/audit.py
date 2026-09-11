"""Persistent semantic audit with recovery-aware, bounded history retention."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import json
import logging
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

LOGGER = logging.getLogger(__name__)
AUDIT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AuditRetentionConfig:
    """Soft byte target, recent history window, and retained mission scopes."""

    max_bytes: int = 16 * 1024 * 1024
    history_records: int = 256
    retained_missions: int = 3

    def __post_init__(self) -> None:
        if self.max_bytes < 0 or self.history_records < 0 or self.retained_missions < 1:
            raise ValueError("audit retention requires non-negative bytes/history and at least one mission")


def add_audit_retention_arguments(parser) -> None:
    """Share retention options between the daemon and standalone server."""

    parser.add_argument("--audit-max-mib", type=int, default=16,
                        help="Semantic audit compaction target in MiB; 0 disables retention. Recovery checkpoints may exceed this target.")
    parser.add_argument("--audit-history-records", type=int, default=256,
                        help="Maximum additional recent history records retained after compaction.")
    parser.add_argument("--audit-retained-missions", type=int, default=3,
                        help="Mission scopes retained after compaction, including the active mission.")


def audit_retention_from_args(args) -> AuditRetentionConfig:
    return AuditRetentionConfig(args.audit_max_mib * 1024 * 1024,
                                args.audit_history_records, args.audit_retained_missions)


def _scope(payload: dict[str, Any]) -> tuple[str, int] | None:
    session = payload.get("audit_session_id")
    generation = payload.get("mission_generation")
    if isinstance(session, str) and session and type(generation) is int:
        return session, generation
    return None


def _checkpoint_keys(record: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
    """Identify cumulative snapshots and coordinator scheduling checkpoints."""

    payload = record["payload"]
    scope = _scope(payload)
    if scope is None:
        return ()
    kind = record.get("record_type")
    if kind in {"operational_plan.execution", "recon.execution"}:
        if payload.get("plan_id") and payload.get("attempt_id"):
            return ((kind, scope, str(payload["plan_id"]), str(payload["attempt_id"])),)
    elif kind == "strategic.diplomacy_state":
        return ((kind, scope),)
    elif kind == "strategic_conflict_cycle":
        coalition = payload.get("coalition")
        if coalition not in {"blue", "red"}:
            return ()
        keys = [(kind, scope, coalition, "schedule"), (kind, scope, coalition, "cycle_number")]
        for attempt in payload.get("attempts", ()):
            if (isinstance(attempt, dict) and attempt.get("candidate_id")
                    and attempt.get("status") != "mission_changed"):
                keys.append((kind, scope, coalition, "candidate", str(attempt["candidate_id"])))
        return tuple(keys)
    return ()


def _cycle_priority(record: dict[str, Any], key: tuple[Any, ...]) -> tuple[float, ...]:
    """Match coordinator recovery ordering even if a cycle was appended late."""

    def number(value, fallback=-math.inf):
        try:
            result = float(value)
            return result if math.isfinite(result) else fallback
        except (TypeError, ValueError):
            return fallback

    payload = record["payload"]
    started = number(payload.get("started_mission_time"))
    cycle = number(payload.get("cycle_number"), 0)
    if key[3] == "cycle_number":
        return (cycle,)
    if key[3] == "schedule":
        return started, cycle
    cooldown = max(
        number(attempt.get("cooldown_until"), math.inf)
        for attempt in payload.get("attempts", ())
        if isinstance(attempt, dict) and str(attempt.get("candidate_id")) == key[4]
        and attempt.get("status") != "mission_changed"
    )
    return started, cooldown


class AuditStore:
    """Append JSONL records and atomically compact superseded audit history."""

    def __init__(self, path: Path | None = None, *,
                 retention: AuditRetentionConfig | None = None,
                 active_scope: tuple[str, int] | None = None) -> None:
        self.path = path
        self.retention = retention or AuditRetentionConfig()
        self.active_scope = active_scope
        self._records: list[dict[str, Any]] = []
        self._sizes: list[int] = []
        self._bytes = 0
        self._disk_bytes = 0
        self._next_compaction = self.retention.max_bytes
        self._load_compacted = False
        self._compactions = 0
        self._protected_bytes = 0
        self._file = None
        self._load()

    def open(self) -> None:
        """Open the append stream when persistent storage is configured."""

        if self.path is None or self._file is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.retention.max_bytes and (self._load_compacted or self._disk_bytes >= self._next_compaction):
            self.compact()
        missing_newline = False
        if self.path.exists() and self.path.stat().st_size:
            with self.path.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                missing_newline = stream.read(1) != b"\n"
        self._file = self.path.open("a", encoding="utf-8", newline="\n")
        if missing_newline:
            self._file.write("\n")
            self._file.flush()
            self._disk_bytes += 1

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
        json_line = _encode(record)
        # Freeze caller-owned payloads so later mutations cannot rewrite history.
        record = json.loads(json_line)
        size = len(json_line.encode("utf-8")) + 1
        if self.path is not None:
            self.open()
            assert self._file is not None
            self._file.write(json_line + "\n")
            self._file.flush()
            self._disk_bytes += size
        self._records.append(record)
        self._sizes.append(size)
        self._bytes += size
        if self.retention.max_bytes and max(self._bytes, self._disk_bytes) >= self._next_compaction:
            try:
                self.compact()
            except OSError:
                # The append already succeeded. Preserve it and retry compaction
                # after further growth rather than failing the recorded action.
                self._next_compaction = max(self._bytes, self._disk_bytes) + self.retention.max_bytes
                LOGGER.exception("Audit compaction failed; retained the existing audit at %s", self.path)
        return record

    def status(self) -> dict[str, Any]:
        """Report retention bounds and any protected-data overshoot."""

        return {
            "path": str(self.path) if self.path is not None else None,
            "retention_enabled": bool(self.retention.max_bytes),
            "max_bytes": self.retention.max_bytes,
            "history_records": self.retention.history_records,
            "retained_missions": self.retention.retained_missions,
            "records": len(self._records),
            "indexed_bytes": self._bytes,
            "file_bytes": self._disk_bytes,
            "protected_bytes": self._protected_bytes,
            "protected_over_target": bool(self.retention.max_bytes and self._protected_bytes > self.retention.max_bytes),
            "compactions": self._compactions,
        }

    def _retained_indices(self) -> tuple[list[int], int]:
        scopes = [self.active_scope] if self.active_scope is not None else []
        for record in reversed(self._records):
            scope = _scope(record["payload"])
            if scope is not None and scope not in scopes and len(scopes) < self.retention.retained_missions:
                scopes.append(scope)
        retained_scopes = set(scopes)
        latest: dict[tuple[Any, ...], int] = {}
        for index, record in enumerate(self._records):
            if _scope(record["payload"]) in retained_scopes:
                for key in _checkpoint_keys(record):
                    previous = latest.get(key)
                    if (previous is None or key[0] != "strategic_conflict_cycle"
                            or _cycle_priority(record, key) >= _cycle_priority(self._records[previous], key)):
                        latest[key] = index
        protected = set(latest.values())
        protected_bytes = sum(self._sizes[index] for index in protected)
        remaining = max(0, self.retention.max_bytes - protected_bytes)
        history = 0
        retained = set(protected)
        for index in range(len(self._records) - 1, -1, -1):
            if history >= self.retention.history_records:
                break
            if index in protected:
                continue
            record = self._records[index]
            scope = _scope(record["payload"])
            if scope is not None and scope not in retained_scopes:
                continue
            # Cumulative snapshots already include their earlier events.
            if _checkpoint_keys(record):
                continue
            size = self._sizes[index]
            if size > remaining:
                break
            retained.add(index)
            remaining -= size
            history += 1
        return sorted(retained), protected_bytes

    def compact(self) -> dict[str, Any]:
        """Keep recovery checkpoints and a recent history tail, atomically on disk."""

        if not self.retention.max_bytes:
            return self.status()
        indices, protected_bytes = self._retained_indices()
        records = [self._records[index] for index in indices]
        sizes = [self._sizes[index] for index in indices]
        total = sum(sizes)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            was_open = self._file is not None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                                 dir=self.path.parent, prefix=self.path.name + ".",
                                                 suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    for record in records:
                        stream.write(_encode(record) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                self.close()
                os.replace(temporary, self.path)
                temporary = None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                if was_open and self._file is None:
                    self._file = self.path.open("a", encoding="utf-8", newline="\n")
            self._disk_bytes = total
        before = self._bytes
        self._records, self._sizes, self._bytes = records, sizes, total
        self._protected_bytes = protected_bytes
        self._compactions += 1
        self._load_compacted = False
        self._next_compaction = max(self.retention.max_bytes, total + max(1, self.retention.max_bytes // 4))
        LOGGER.info("Audit compacted: %s -> %s bytes, %s records, %s protected bytes",
                    before, total, len(records), protected_bytes)
        if protected_bytes > self.retention.max_bytes:
            LOGGER.warning("Audit recovery checkpoints exceed the byte target; preserving %s bytes", protected_bytes)
        return self.status()

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
                    if not isinstance(record.get("record_type"), str) or not record["record_type"].strip():
                        raise ValueError("record_type must be a non-empty string")
                    if record.get("schema_version") != AUDIT_SCHEMA_VERSION:
                        raise ValueError(f"unsupported schema version {record.get('schema_version')!r}")
                    self._records.append(record)
                    size = len(_encode(record).encode("utf-8")) + 1
                    self._sizes.append(size)
                    self._bytes += size
                    # Bound startup indexing without rewriting a file still being
                    # read. The final atomic rewrite happens when the store opens.
                    if self.retention.max_bytes and self._bytes >= self._next_compaction:
                        indices, self._protected_bytes = self._retained_indices()
                        self._records = [self._records[index] for index in indices]
                        self._sizes = [self._sizes[index] for index in indices]
                        self._bytes = sum(self._sizes)
                        self._next_compaction = max(self.retention.max_bytes, self._bytes + max(1, self.retention.max_bytes // 4))
                        self._load_compacted = True
                except (ValueError, json.JSONDecodeError) as exc:
                    LOGGER.warning("Ignoring invalid audit record %s:%s: %s", self.path, line_number, exc)
        self._disk_bytes = self.path.stat().st_size


def _encode(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def latest_attempt_records(records: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Collapse execution snapshots to the latest record for each attempt id."""

    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        attempt_id = str(payload.get("attempt_id") or "")
        if attempt_id:
            latest[(record.get("record_type"), _scope(payload), payload.get("plan_id"), attempt_id)] = record
    return tuple(
        sorted(
            latest.values(),
            key=lambda record: (
                int(record["payload"].get("attempt_number") or 0),
                str(record.get("recorded_at") or ""),
            ),
        )
    )


__all__ = ["AUDIT_SCHEMA_VERSION", "AuditRetentionConfig", "AuditStore", "latest_attempt_records"]
