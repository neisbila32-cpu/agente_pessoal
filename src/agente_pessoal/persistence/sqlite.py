"""Persistência SQLite para tarefas, auditoria e permissões."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from agente_pessoal.audit.events import AuditEvent, AuditEventType
from agente_pessoal.core.interpretation import RequestInterpretation
from agente_pessoal.core.request import UserRequest
from agente_pessoal.core.task import (
    StepResult,
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)
from agente_pessoal.persistence.records import TaskStatusChange
from agente_pessoal.security.permissions import Permission, PermissionGrant


def _date(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class SQLiteStore:
    """Repositório SQLite único, compartilhável pelos ports do núcleo e segurança."""

    def __init__(self, database_path: str | Path) -> None:
        raw_path = str(database_path)
        self.database_path = (
            raw_path if raw_path == ":memory:" else str(Path(raw_path).expanduser())
        )
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_requests (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL REFERENCES user_requests(id),
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT,
                    interpretation_json TEXT
                );
                CREATE TABLE IF NOT EXISTS task_steps (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS task_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    task_id TEXT,
                    step_id TEXT,
                    tool_name TEXT,
                    permission TEXT,
                    outcome TEXT,
                    error_type TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_events(task_id, id);
                CREATE TABLE IF NOT EXISTS permissions (
                    permission TEXT PRIMARY KEY,
                    granted INTEGER NOT NULL,
                    granted_at TEXT,
                    granted_by TEXT,
                    revoked_at TEXT,
                    revoked_by TEXT
                );
                """
            )
            task_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "interpretation_json" not in task_columns:
                self._connection.execute(
                    "ALTER TABLE tasks ADD COLUMN interpretation_json TEXT"
                )

    def create_task(self, request: UserRequest, task: Task) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO user_requests(id, text, received_at) VALUES (?, ?, ?)",
                (request.id, request.text, request.received_at.isoformat()),
            )
            self._connection.execute(
                "INSERT INTO tasks(id, request_id, status, created_at, completed_at, error, "
                "interpretation_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    request.id,
                    task.status.value,
                    task.created_at.isoformat(),
                    _date(task.completed_at),
                    task.error,
                    self._encode_interpretation(task.interpretation),
                ),
            )
            self._connection.execute(
                "INSERT INTO task_status_history(task_id, status, changed_at) VALUES (?, ?, ?)",
                (task.id, task.status.value, task.created_at.isoformat()),
            )

    def save_task(self, task: Task) -> None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT status FROM tasks WHERE id = ?", (task.id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Tarefa não persistida: {task.id}")
            previous_status = TaskStatus(row["status"])
            self._connection.execute(
                "UPDATE tasks SET status = ?, completed_at = ?, error = ?, "
                "interpretation_json = ? WHERE id = ?",
                (
                    task.status.value,
                    _date(task.completed_at),
                    task.error,
                    self._encode_interpretation(task.interpretation),
                    task.id,
                ),
            )
            if previous_status != task.status:
                self._connection.execute(
                    "INSERT INTO task_status_history(task_id, status, changed_at) VALUES (?, ?, ?)",
                    (task.id, task.status.value, datetime.now(timezone.utc).isoformat()),
                )
            self._connection.execute("DELETE FROM task_steps WHERE task_id = ?", (task.id,))
            self._connection.executemany(
                """INSERT INTO task_steps(
                    id, task_id, position, description, tool_name, arguments_json,
                    status, result_json, error, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        step.id,
                        task.id,
                        position,
                        step.description,
                        step.tool_name,
                        _json_dump(dict(step.arguments)),
                        step.status.value,
                        _json_dump(step.result) if step.status is StepStatus.COMPLETED else None,
                        step.error,
                        _date(step.started_at),
                        _date(step.completed_at),
                    )
                    for position, step in enumerate(task.steps)
                ],
            )

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT t.*, r.text FROM tasks t
                   JOIN user_requests r ON r.id = t.request_id WHERE t.id = ?""",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            task = Task(
                request=row["text"],
                id=row["id"],
                request_id=row["request_id"],
                status=TaskStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                error=row["error"],
                completed_at=_parse_date(row["completed_at"]),
                interpretation=self._decode_interpretation(row["interpretation_json"]),
            )
            steps = self._connection.execute(
                "SELECT * FROM task_steps WHERE task_id = ? ORDER BY position", (task_id,)
            ).fetchall()
            for item in steps:
                result = json.loads(item["result_json"]) if item["result_json"] is not None else None
                step = TaskStep(
                    id=item["id"],
                    description=item["description"],
                    tool_name=item["tool_name"],
                    arguments=json.loads(item["arguments_json"]),
                    status=StepStatus(item["status"]),
                    result=result,
                    error=item["error"],
                    started_at=_parse_date(item["started_at"]),
                    completed_at=_parse_date(item["completed_at"]),
                )
                task.steps.append(step)
                if step.status is StepStatus.COMPLETED:
                    task.results.append(
                        StepResult(
                            step_id=step.id,
                            tool_name=step.tool_name,
                            value=step.result,
                            created_at=step.completed_at or task.created_at,
                        )
                    )
            return task

    def list_tasks(self) -> tuple[Task, ...]:
        with self._lock:
            ids = self._connection.execute(
                "SELECT id FROM tasks ORDER BY created_at, id"
            ).fetchall()
        return tuple(task for row in ids if (task := self.get_task(row["id"])) is not None)

    def get_status_history(self, task_id: str) -> tuple[TaskStatusChange, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, changed_at FROM task_status_history "
                "WHERE task_id = ? ORDER BY id",
                (task_id,),
            ).fetchall()
        return tuple(
            TaskStatusChange(TaskStatus(row["status"]), datetime.fromisoformat(row["changed_at"]))
            for row in rows
        )

    def append_audit_event(self, event: AuditEvent) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO audit_events(
                    event_type, occurred_at, task_id, step_id, tool_name,
                    permission, outcome, error_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_type.value,
                    event.occurred_at.isoformat(),
                    event.task_id,
                    event.step_id,
                    event.tool_name,
                    event.permission,
                    event.outcome,
                    event.error_type,
                ),
            )

    def list_audit_events(self, task_id: str | None = None) -> tuple[AuditEvent, ...]:
        with self._lock:
            if task_id is None:
                rows = self._connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM audit_events WHERE task_id = ? ORDER BY id", (task_id,)
                ).fetchall()
        return tuple(
            AuditEvent(
                event_type=AuditEventType(row["event_type"]),
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                task_id=row["task_id"],
                step_id=row["step_id"],
                tool_name=row["tool_name"],
                permission=row["permission"],
                outcome=row["outcome"],
                error_type=row["error_type"],
            )
            for row in rows
        )

    def grant_permission(self, grant: PermissionGrant) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO permissions(
                    permission, granted, granted_at, granted_by, revoked_at, revoked_by
                ) VALUES (?, 1, ?, ?, NULL, NULL)
                ON CONFLICT(permission) DO UPDATE SET
                    granted=1, granted_at=excluded.granted_at,
                    granted_by=excluded.granted_by, revoked_at=NULL, revoked_by=NULL""",
                (grant.permission.value, _date(grant.granted_at), grant.granted_by),
            )

    def revoke_permission(
        self, permission: Permission, revoked_by: str, revoked_at: str
    ) -> bool:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT granted FROM permissions WHERE permission = ?", (permission.value,)
            ).fetchone()
            was_granted = bool(row and row["granted"])
            self._connection.execute(
                """INSERT INTO permissions(
                    permission, granted, revoked_at, revoked_by
                ) VALUES (?, 0, ?, ?)
                ON CONFLICT(permission) DO UPDATE SET
                    granted=0, revoked_at=excluded.revoked_at, revoked_by=excluded.revoked_by""",
                (permission.value, revoked_at, revoked_by),
            )
            return was_granted

    def get_permission(self, permission: Permission) -> PermissionGrant | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM permissions WHERE permission = ?", (permission.value,)
            ).fetchone()
        return self._permission_from_row(row) if row else None

    def list_permissions(self, include_revoked: bool = False) -> tuple[PermissionGrant, ...]:
        query = "SELECT * FROM permissions"
        if not include_revoked:
            query += " WHERE granted = 1"
        query += " ORDER BY permission"
        with self._lock:
            rows = self._connection.execute(query).fetchall()
        return tuple(self._permission_from_row(row) for row in rows)

    @staticmethod
    def _permission_from_row(row: sqlite3.Row) -> PermissionGrant:
        return PermissionGrant(
            permission=Permission(row["permission"]),
            granted=bool(row["granted"]),
            granted_at=_parse_date(row["granted_at"]),
            granted_by=row["granted_by"],
            revoked_at=_parse_date(row["revoked_at"]),
            revoked_by=row["revoked_by"],
        )

    @staticmethod
    def _encode_interpretation(
        interpretation: RequestInterpretation | None,
    ) -> str | None:
        if interpretation is None:
            return None
        return _json_dump(
            {
                "objective": interpretation.objective,
                "intent": interpretation.intent,
                "required_information": list(interpretation.required_information),
                "limitations": list(interpretation.limitations),
                "ambiguities": list(interpretation.ambiguities),
                "requires_clarification": interpretation.requires_clarification,
            }
        )

    @staticmethod
    def _decode_interpretation(value: str | None) -> RequestInterpretation | None:
        if value is None:
            return None
        data = json.loads(value)
        return RequestInterpretation(
            objective=data["objective"],
            intent=data["intent"],
            required_information=tuple(data["required_information"]),
            limitations=tuple(data["limitations"]),
            ambiguities=tuple(data["ambiguities"]),
            requires_clarification=data["requires_clarification"],
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
