import tempfile
import unittest
from pathlib import Path

from agente_pessoal.audit import AuditEventType, AuditLogger
from agente_pessoal.core import (
    PlannedStep,
    RequestInterpretation,
    TaskOrchestrator,
    TaskPlan,
    TaskStatus,
    UserRequest,
)
from agente_pessoal.core.executor import ToolExecutor
from agente_pessoal.core.task_manager import TaskManager
from agente_pessoal.persistence import SQLiteStore
from agente_pessoal.security import Permission, PermissionDenied, PermissionManager


class ControlledPlanner:
    def plan(self, request):
        return TaskPlan(
            steps=(
                PlannedStep(
                    "Processamento controlado",
                    "controlled",
                    {"value": "private-input"},
                ),
            ),
            interpretation=RequestInterpretation(
                objective="Validar persistência",
                intent="teste",
                limitations=("ferramenta controlada",),
            ),
        )


class ControlledTool:
    name = "controlled"
    required_permission = Permission.FILE_READ

    def __init__(self):
        self.calls = []

    def describe(self):
        return "Ferramenta controlada de teste"

    def execute(self, arguments):
        self.calls.append(arguments)
        return {"result": "private-output"}


class ApprovalStub:
    def __init__(self, approved):
        self.approved = approved
        self.requests = []

    def request_approval(self, permission, reason):
        self.requests.append((permission, reason))
        return self.approved


class PersistenceAuditPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1]
        )
        self.database = Path(self.temp_dir.name) / "agent.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_task_and_history_survive_store_reinitialization(self):
        store = SQLiteStore(self.database)
        audit = AuditLogger(store)
        permissions = PermissionManager(store, audit)
        permissions.grant(Permission.FILE_READ)
        tool = ControlledTool()
        manager = TaskManager(
            ControlledPlanner(),
            ToolExecutor([tool], permissions, audit),
            repository=store,
            audit=audit,
        )
        task = TaskOrchestrator(manager).handle("Solicitação persistida")
        task_id = task.id
        store.close()

        reopened_store = SQLiteStore(self.database)
        recovered_manager = TaskManager(
            ControlledPlanner(),
            ToolExecutor([], PermissionManager(reopened_store)),
            repository=reopened_store,
        )
        recovered = recovered_manager.get(task_id)

        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.status, TaskStatus.COMPLETED)
        self.assertEqual(recovered.description, "Solicitação persistida")
        self.assertEqual(recovered.steps[0].arguments["value"], "private-input")
        self.assertEqual(recovered.results[0].value, {"result": "private-output"})
        self.assertEqual(recovered.interpretation.objective, "Validar persistência")
        self.assertEqual(
            [change.status for change in reopened_store.get_status_history(task_id)],
            [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.COMPLETED],
        )
        self.assertTrue(
            PermissionManager(reopened_store).list_permissions()[0].granted
        )
        self.assertIn(
            AuditEventType.TASK_CREATED,
            [event.event_type for event in reopened_store.list_audit_events(task_id)],
        )
        reopened_store.close()

    def test_audit_tracks_execution_without_recording_arguments_or_results(self):
        store = SQLiteStore(self.database)
        audit = AuditLogger(store)
        permissions = PermissionManager(store, audit)
        permissions.grant(Permission.FILE_READ)
        manager = TaskManager(
            ControlledPlanner(),
            ToolExecutor([ControlledTool()], permissions, audit),
            repository=store,
            audit=audit,
        )

        task = manager.submit(UserRequest("pedido com dado privado"))
        events = store.list_audit_events(task.id)
        event_types = [event.event_type for event in events]
        serialized_events = repr(events)

        self.assertIn(AuditEventType.TASK_CREATED, event_types)
        self.assertIn(AuditEventType.STEP_STARTED, event_types)
        self.assertIn(AuditEventType.TOOL_ATTEMPTED, event_types)
        self.assertIn(AuditEventType.PERMISSION_CHECKED, event_types)
        self.assertIn(AuditEventType.STEP_COMPLETED, event_types)
        self.assertNotIn("private-input", serialized_events)
        self.assertNotIn("private-output", serialized_events)
        self.assertNotIn("pedido com dado privado", serialized_events)
        store.close()

    def test_permission_grant_revoke_and_denial_persist(self):
        store = SQLiteStore(self.database)
        audit = AuditLogger(store)
        permissions = PermissionManager(store, audit)
        permissions.grant(Permission.FILE_READ, granted_by="user")
        self.assertEqual([g.permission for g in permissions.list_permissions()], [Permission.FILE_READ])
        self.assertTrue(permissions.revoke(Permission.FILE_READ, revoked_by="user"))
        self.assertEqual(permissions.list_permissions(), ())
        self.assertFalse(permissions.revoke(Permission.FILE_READ))
        self.assertFalse(permissions.list_permissions(include_revoked=True)[0].granted)

        with self.assertRaises(PermissionDenied):
            permissions.require(Permission.FILE_READ)

        event_types = [event.event_type for event in store.list_audit_events()]
        self.assertIn(AuditEventType.PERMISSION_GRANTED, event_types)
        self.assertIn(AuditEventType.PERMISSION_REVOKED, event_types)
        self.assertIn(AuditEventType.AUTHORIZATION_DENIED, event_types)
        store.close()
        reopened = SQLiteStore(self.database)
        persisted = PermissionManager(reopened).list_permissions(include_revoked=True)
        self.assertEqual(len(persisted), 1)
        self.assertFalse(persisted[0].granted)
        reopened.close()

    def test_revoked_permission_blocks_tool_before_execution(self):
        store = SQLiteStore(self.database)
        audit = AuditLogger(store)
        permissions = PermissionManager(store, audit)
        permissions.grant(Permission.FILE_READ)
        permissions.revoke(Permission.FILE_READ)
        tool = ControlledTool()
        manager = TaskManager(
            ControlledPlanner(),
            ToolExecutor([tool], permissions, audit),
            repository=store,
            audit=audit,
        )

        task = manager.submit(UserRequest("tentar operação"))

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(tool.calls, [])
        denied_checks = [
            event
            for event in store.list_audit_events(task.id)
            if event.event_type is AuditEventType.PERMISSION_CHECKED
        ]
        self.assertEqual(denied_checks[0].outcome, "denied")
        store.close()
        reopened = SQLiteStore(self.database)
        recovered = reopened.get_task(task.id)
        self.assertEqual(recovered.status, TaskStatus.FAILED)
        self.assertIn("PermissionDenied", recovered.steps[0].error)
        reopened.close()

    def test_approval_provider_is_an_injectable_interface(self):
        store = SQLiteStore(self.database)
        approval = ApprovalStub(approved=True)
        manager = PermissionManager(store, approval_provider=approval)

        manager.require(Permission.FILE_READ, reason="ação controlada")

        self.assertEqual(approval.requests, [(Permission.FILE_READ, "ação controlada")])
        self.assertTrue(store.get_permission(Permission.FILE_READ).granted)
        store.close()

    def test_approval_provider_failure_is_audited_and_denied(self):
        class BrokenApproval:
            def request_approval(self, permission, reason):
                raise RuntimeError("erro com informação privada")

        store = SQLiteStore(self.database)
        manager = PermissionManager(store, AuditLogger(store), BrokenApproval())

        with self.assertRaises(PermissionDenied):
            manager.require(Permission.FILE_READ, reason="operação")

        events = store.list_audit_events()
        denial = [event for event in events if event.event_type is AuditEventType.AUTHORIZATION_DENIED]
        self.assertEqual(denial[0].error_type, "RuntimeError")
        self.assertNotIn("informação privada", repr(events))
        store.close()


if __name__ == "__main__":
    unittest.main()
