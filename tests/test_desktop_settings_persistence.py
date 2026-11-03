import sqlite3
import tempfile
import unittest
from pathlib import Path

from agente_pessoal.desktop.services import DesktopApplicationServices
from agente_pessoal.integrations import (
    AgentConnectionBindingRegistry,
    ConnectionRegistry,
    ProviderRegistry,
)
from agente_pessoal.integrations.bindings import DuplicateBindingError
from agente_pessoal.integrations.adapters.codex import CODEX_PROVIDER_ID, register_codex_provider
from agente_pessoal.integrations.adapters.gemini_cli import register_gemini_provider
from agente_pessoal.multiagent import AgentRegistry
from agente_pessoal.persistence import (
    DesktopAgentBindingRecord,
    DesktopAgentRecord,
    DesktopPreferenceRecord,
    SQLiteStore,
)


def make_services(database_path, *, include_demo_agents=True):
    providers = ProviderRegistry()
    register_codex_provider(providers)
    register_gemini_provider(providers)
    agents = AgentRegistry()
    connections = ConnectionRegistry(providers)
    bindings = AgentConnectionBindingRegistry(agents, connections)
    store = SQLiteStore(database_path)
    services = DesktopApplicationServices(
        provider_registry=providers,
        agent_registry=agents,
        connection_registry=connections,
        binding_registry=bindings,
        settings_store=store,
        include_demo_agents=include_demo_agents,
    )
    return services, store


class DesktopSettingsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.database = Path(self.temp_dir.name) / "desktop.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_personal(self, services, *, provider_id="google-gemini-cli"):
        return services.register_agent(
            agent_id="assistente-pessoal",
            name="Assistente pessoal",
            description="Apoio textual local configurado pelo usuário.",
            capabilities=("texto", "resumo"),
            provider_id=provider_id,
        )

    def test_agent_fields_and_provider_binding_survive_reopen_without_auth_state(self):
        services, store = make_services(self.database)
        agent = self.add_personal(services)
        services.set_agent_enabled(agent.id, False)
        store.close()

        restored, reopened = make_services(self.database)
        personal = restored.agents.get(agent.id)
        links = restored.bindings_for(agent.id)

        self.assertEqual(personal.name, "Assistente pessoal")
        self.assertEqual(personal.description, "Apoio textual local configurado pelo usuário.")
        self.assertEqual(personal.capabilities, ("texto", "resumo"))
        self.assertFalse(personal.enabled)
        self.assertEqual(personal.adapter_id, "personal:assistente-pessoal")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].connection_id, "desktop-google-gemini-cli")
        self.assertEqual(
            reopened.load_desktop_settings().agents,
            (DesktopAgentRecord(agent.id, agent.name, agent.description, agent.capabilities, False),),
        )
        self.assertTrue(all(not connection.account_id for connection in restored.list_connections()))
        self.assertTrue(all(connection.verification_status.value == "unverified" for connection in restored.list_connections()))
        self.assertEqual(reopened._connection.execute("SELECT COUNT(*) FROM permissions").fetchone()[0], 0)
        with self.assertRaises(LookupError):
            restored.executors.get(personal.adapter_id)
        reopened.close()

    def test_update_and_enable_state_are_persisted_and_delete_cascades_bindings(self):
        services, store = make_services(self.database)
        agent = self.add_personal(services)
        updated = services.update_agent(
            agent.id,
            name="Revisor pessoal",
            description="Descrição atualizada.",
            capabilities=("revisão", "texto"),
        )
        services.set_agent_enabled(updated.id, False)
        store.close()

        restored, reopened = make_services(self.database)
        self.assertEqual(restored.agents.get(agent.id).name, "Revisor pessoal")
        self.assertEqual(restored.agents.get(agent.id).capabilities, ("revisão", "texto"))
        self.assertFalse(restored.agents.get(agent.id).enabled)
        restored.delete_agent(agent.id)
        snapshot = reopened.load_desktop_settings()
        self.assertEqual(snapshot.agents, ())
        self.assertEqual(snapshot.bindings, ())
        with self.assertRaises(ValueError):
            restored.delete_agent("demo-planejador")
        with self.assertRaises(ValueError):
            restored.update_agent(
                "demo-planejador",
                name="Alterado",
                description="Não permitido",
                capabilities=("texto",),
            )
        reopened.close()

    def test_demo_agents_are_recreated_but_never_persisted(self):
        services, store = make_services(self.database)
        self.assertFalse(services.is_personal_agent("demo-planejador"))
        self.assertEqual(store.load_desktop_settings().agents, ())
        store.close()

        restored, reopened = make_services(self.database)
        self.assertIsNotNone(restored.agents.get("demo-planejador"))
        self.assertFalse(restored.is_personal_agent("demo-planejador"))
        self.assertEqual(reopened.load_desktop_settings().agents, ())
        reopened.close()

    def test_binding_added_later_is_persisted_and_duplicate_is_rejected(self):
        services, store = make_services(self.database)
        services.register_agent(
            agent_id="sem-vinculo",
            name="Sem vínculo",
            description="Agente pessoal sem associação.",
            capabilities=("texto",),
        )
        services.bind_agent("sem-vinculo", CODEX_PROVIDER_ID)
        with self.assertRaises(DuplicateBindingError):
            services.bind_agent("sem-vinculo", CODEX_PROVIDER_ID)
        self.assertEqual(len(store.load_desktop_settings().bindings), 1)
        store.close()

        restored, reopened = make_services(self.database)
        self.assertEqual(
            restored.bindings_for("sem-vinculo")[0].connection_id,
            "desktop-openai-codex",
        )
        reopened.close()

    def test_invalid_agent_records_and_missing_connection_references_are_skipped(self):
        store = SQLiteStore(self.database)
        store.save_desktop_agent(
            DesktopAgentRecord("valido", "Válido", "Registro bom.", ("texto",), True)
        )
        store.save_desktop_binding(
            DesktopAgentBindingRecord("valido", "conexao-removida")
        )
        with store._lock, store._connection:
            store._connection.execute(
                "INSERT INTO desktop_personal_agents VALUES (?, ?, ?, ?, ?)",
                ("corrompido", "Inválido", "Capabilities não JSON", "{", 1),
            )
        store.close()

        restored, reopened = make_services(self.database)

        self.assertIsNotNone(restored.agents.get("valido"))
        self.assertNotIn("corrompido", {agent.id for agent in restored.list_agents()})
        self.assertEqual(restored.bindings_for("valido"), ())
        self.assertGreaterEqual(len(restored.settings_warnings), 2)
        reopened.close()

    def test_migration_from_existing_unversioned_task_database_preserves_rows(self):
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE user_requests (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, received_at TEXT NOT NULL
            );
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES user_requests(id),
                status TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT, error TEXT
            );
            INSERT INTO user_requests VALUES ('request-old', 'pedido existente', '2025-01-01T00:00:00+00:00');
            INSERT INTO tasks VALUES ('task-old', 'request-old', 'pending', '2025-01-01T00:00:00+00:00', NULL, NULL);
            PRAGMA user_version = 0;
            """
        )
        connection.close()

        store = SQLiteStore(self.database)
        self.assertEqual(store._connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(
            store._connection.execute("SELECT text FROM user_requests WHERE id = 'request-old'").fetchone()[0],
            "pedido existente",
        )
        task_columns = {
            row["name"] for row in store._connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        self.assertIn("interpretation_json", task_columns)
        self.assertEqual(store.load_desktop_settings().agents, ())
        store.close()

    def test_invalid_references_never_create_agent_permissions(self):
        services, store = make_services(self.database)
        self.add_personal(services)
        self.assertEqual(store._connection.execute("SELECT COUNT(*) FROM permissions").fetchone()[0], 0)
        self.assertFalse(hasattr(services, "permission_manager"))
        store.close()

    def test_allowlisted_window_size_preference_persists_and_invalid_values_are_rejected(self):
        store = SQLiteStore(self.database)
        store.save_desktop_preference(DesktopPreferenceRecord("window_size", "1280x800"))
        self.assertEqual(
            store.load_desktop_settings().preferences,
            (DesktopPreferenceRecord("window_size", "1280x800"),),
        )
        with self.assertRaises(ValueError):
            DesktopPreferenceRecord("api_key", "secret")
        with self.assertRaises(ValueError):
            DesktopPreferenceRecord("window_size", "small")
        store.close()


if __name__ == "__main__":
    unittest.main()
