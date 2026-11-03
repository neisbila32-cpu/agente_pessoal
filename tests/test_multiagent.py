import ast
from pathlib import Path
import unittest

from agente_pessoal.multiagent import (
    AgentDefinition,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentNotFoundError,
    AgentRegistry,
    DuplicateAgentError,
)


def definition(**overrides):
    values = {
        "id": "research",
        "name": "Pesquisa",
        "description": "Agente de pesquisa",
        "capabilities": ("search", "summarize"),
        "adapter_id": "local.research",
    }
    values.update(overrides)
    return AgentDefinition(**values)


class AgentRegistryTests(unittest.TestCase):
    def test_register_get_and_list(self):
        registry = AgentRegistry()
        agent = definition()

        self.assertIs(registry.register(agent), agent)
        self.assertEqual(registry.get(agent.id), agent)
        self.assertEqual(registry.list_agents(), (agent,))

    def test_duplicate_identifier_is_rejected(self):
        registry = AgentRegistry()
        registry.register(definition())

        with self.assertRaises(DuplicateAgentError):
            registry.register(definition(name="Outro nome"))

    def test_missing_identifier_is_rejected_for_lookup_and_state_changes(self):
        registry = AgentRegistry()

        for operation in (registry.get, registry.enable, registry.disable):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(AgentNotFoundError):
                    operation("missing")

    def test_enable_and_disable_replace_immutable_definition(self):
        registry = AgentRegistry()
        disabled = registry.register(definition(enabled=False))

        enabled = registry.enable(disabled.id)
        self.assertTrue(enabled.enabled)
        self.assertFalse(disabled.enabled)
        self.assertTrue(registry.get(disabled.id).enabled)

        disabled_again = registry.disable(disabled.id)
        self.assertFalse(disabled_again.enabled)


class MultiAgentModelTests(unittest.TestCase):
    def test_agent_definition_validates_required_text_and_capabilities(self):
        with self.assertRaises(ValueError):
            definition(id=" ")
        with self.assertRaises(ValueError):
            definition(capabilities=("search", " "))

    def test_execution_request_and_result_are_typed_and_validated(self):
        request = AgentExecutionRequest(agent_id="research", input="Resuma")
        result = AgentExecutionResult(
            request_id=request.id,
            agent_id=request.agent_id,
            status=AgentExecutionStatus.COMPLETED,
            output="Resumo",
        )
        self.assertEqual(result.output, "Resumo")
        with self.assertRaises(ValueError):
            AgentExecutionRequest(agent_id="research", input=" ")
        with self.assertRaises(ValueError):
            AgentExecutionResult("request", "research", "completed")

    def test_multiagent_package_has_no_core_ai_or_persistence_imports(self):
        package = Path(__file__).parents[1] / "src" / "agente_pessoal" / "multiagent"
        imported_roots = set()
        for module_path in package.glob("*.py"):
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".")[1:2][0] if node.module.startswith("agente_pessoal.") else node.module)
                elif isinstance(node, ast.Import):
                    imported_roots.update(alias.name.split(".")[1:2][0] if alias.name.startswith("agente_pessoal.") else alias.name for alias in node.names)
        self.assertTrue(imported_roots.isdisjoint({"core", "ai", "persistence", "security"}))


if __name__ == "__main__":
    unittest.main()
