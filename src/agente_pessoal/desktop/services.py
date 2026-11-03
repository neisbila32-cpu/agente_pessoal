"""Composição dos serviços usados pela interface desktop."""

from dataclasses import dataclass, replace

from agente_pessoal.integrations import (
    AgentConnectionBindingRegistry,
    AuthenticationMethod,
    ConnectionRegistry,
    ConnectionService,
    ConnectionStatus,
    ConnectionVerificationStatus,
    ConnectionVerifierRegistry,
    ProviderConnection,
    ProviderRegistry,
)
from agente_pessoal.integrations.adapters.codex import (
    CODEX_PROVIDER_ID,
    CodexAccountState,
    CodexAuthService,
    CodexConnectionVerifier,
    CodexLoginMethod,
    CodexLoginResult,
    CodexLoginState,
    register_codex_provider,
)
from agente_pessoal.integrations.adapters.gemini_cli import (
    GEMINI_PROVIDER_ID,
    GeminiCliAdapter,
    register_gemini_provider,
)
from agente_pessoal.integrations.diagnostics import IntegrationDiagnostics
from agente_pessoal.multiagent import (
    AgentDefinition,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentExecutorRegistry,
    AgentRegistry,
    MultiAgentPlan,
    MultiAgentResult,
    MultiAgentWorkflow,
    AgentTask,
    TaskDependency,
    MaestroCoordinator,
)
from agente_pessoal.persistence import DesktopAgentBindingRecord, DesktopAgentRecord, SQLiteStore
from agente_pessoal.security import (
    AuthorizationContext,
    Permission,
    PermissionPolicy,
)


CODEX_CONNECTION_ID = "desktop-openai-codex"
GEMINI_CONNECTION_ID = "desktop-google-gemini-cli"


@dataclass(frozen=True, slots=True)
class CodexLoginCompletion:
    login: CodexLoginResult
    account_state: CodexAccountState | None


class _DemonstrationExecutor:
    """Executor determinístico sem modelo, rede, filesystem ou comandos."""

    def __init__(self, label: str) -> None:
        self._label = label

    def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        prior = request.metadata.get("prior_results", {})
        prior_count = len(prior) if isinstance(prior, dict) else 0
        return AgentExecutionResult(
            request_id=request.id,
            agent_id=request.agent_id,
            status=AgentExecutionStatus.COMPLETED,
            output=(
                f"[SIMULAÇÃO — {self._label}] Etapa concluída; "
                f"contexto recebido de {prior_count} etapa(s) anterior(es)."
            ),
        )


class DesktopApplicationServices:
    """Serviços de UI montados por injeção; nenhuma tarefa é iniciada no construtor."""

    DEMO_AGENTS = (
        ("demo-planejador", "Planejador demonstrativo", "Organiza uma solicitação em etapas simuladas.", "demo.planner"),
        ("demo-revisor", "Revisor demonstrativo", "Revisa o contexto de outra etapa simulada.", "demo.reviewer"),
        ("demo-sintetizador", "Sintetizador demonstrativo", "Consolida os resultados simulados.", "demo.synthesizer"),
    )

    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry | None = None,
        agent_registry: AgentRegistry | None = None,
        connection_registry: ConnectionRegistry | None = None,
        binding_registry: AgentConnectionBindingRegistry | None = None,
        executor_registry: AgentExecutorRegistry | None = None,
        codex_auth: CodexAuthService | None = None,
        gemini_cli: GeminiCliAdapter | None = None,
        diagnostics: IntegrationDiagnostics | None = None,
        settings_store: SQLiteStore | None = None,
        settings_warnings: tuple[str, ...] = (),
        include_demo_agents: bool = True,
    ) -> None:
        self.providers = provider_registry or ProviderRegistry()
        self._ensure_provider(self.providers, CODEX_PROVIDER_ID, register_codex_provider)
        self._ensure_provider(self.providers, GEMINI_PROVIDER_ID, register_gemini_provider)

        self.codex_auth = codex_auth or CodexAuthService()
        self.gemini_cli = gemini_cli or GeminiCliAdapter()
        self.connections = connection_registry or ConnectionRegistry(self.providers)
        self._ensure_connection(
            CODEX_CONNECTION_ID,
            CODEX_PROVIDER_ID,
            AuthenticationMethod.BROWSER_LOGIN,
        )
        self._ensure_connection(
            GEMINI_CONNECTION_ID,
            GEMINI_PROVIDER_ID,
            AuthenticationMethod.BROWSER_LOGIN,
        )

        self.agents = agent_registry or AgentRegistry()
        self.bindings = binding_registry or AgentConnectionBindingRegistry(self.agents, self.connections)
        self.executors = executor_registry or AgentExecutorRegistry()
        self.settings_store = settings_store
        self.settings_warnings = list(settings_warnings)
        self._personal_agent_ids: set[str] = set()
        if include_demo_agents:
            self._register_demo_agents()
        if self.settings_store is not None:
            self._restore_personal_settings()

        self.diagnostics = diagnostics or IntegrationDiagnostics(
            self.providers,
            self.codex_auth,
            self.gemini_cli,
        )
    @staticmethod
    def _ensure_provider(registry, provider_id, register) -> None:
        try:
            registry.get(provider_id)
        except LookupError:
            register(registry)

    def _ensure_connection(self, connection_id, provider_id, method) -> None:
        if any(item.id == connection_id for item in self.connections.list_connections()):
            return
        self.connections.register(
            ProviderConnection(
                id=connection_id,
                provider_id=provider_id,
                authentication_method=method,
            )
        )

    def _register_demo_agents(self) -> None:
        for agent_id, name, description, adapter_id in self.DEMO_AGENTS:
            try:
                self.agents.get(agent_id)
            except LookupError:
                self.agents.register(
                    AgentDefinition(
                        id=agent_id,
                        name=name,
                        description=description,
                        capabilities=("demonstração", "texto"),
                        adapter_id=adapter_id,
                    )
                )
            try:
                self.executors.get(adapter_id)
            except LookupError:
                self.executors.register(adapter_id, _DemonstrationExecutor(name))

    def _restore_personal_settings(self) -> None:
        try:
            snapshot = self.settings_store.load_desktop_settings()
        except Exception:
            self.settings_warnings.append(
                "As configurações locais não puderam ser carregadas; a aplicação iniciou sem elas."
            )
            return
        self.settings_warnings.extend(snapshot.issues)
        demo_ids = {item[0] for item in self.DEMO_AGENTS}
        for record in snapshot.agents:
            try:
                if record.id in demo_ids:
                    raise ValueError("ID reservado para agente demonstrativo.")
                self.agents.register(
                    AgentDefinition(
                        id=record.id,
                        name=record.name,
                        description=record.description,
                        capabilities=record.capabilities,
                        adapter_id=f"personal:{record.id}",
                        enabled=record.enabled,
                    )
                )
                self._personal_agent_ids.add(record.id)
            except Exception:
                self.settings_warnings.append(
                    "Uma configuração de agente inválida ou duplicada foi ignorada."
                )
        for record in snapshot.bindings:
            if record.agent_id not in self._personal_agent_ids:
                self.settings_warnings.append("Um vínculo sem agente pessoal foi ignorado.")
                continue
            try:
                self.connections.get(record.connection_id)
                self.bindings.register(record.agent_id, record.connection_id)
            except Exception:
                self.settings_warnings.append(
                    "Um vínculo com conexão ausente ou inválida foi ignorado."
                )

    def list_agents(self) -> tuple[AgentDefinition, ...]:
        return self.agents.list_agents()

    def list_connections(self) -> tuple[ProviderConnection, ...]:
        return self.connections.list_connections()

    def bindings_for(self, agent_id: str):
        return self.bindings.list_bindings(agent_id)

    def register_agent(
        self,
        *,
        agent_id: str,
        name: str,
        description: str,
        capabilities: tuple[str, ...],
        provider_id: str | None = None,
    ) -> AgentDefinition:
        if provider_id is not None:
            self.providers.get(provider_id)
            connection_id = {
                CODEX_PROVIDER_ID: CODEX_CONNECTION_ID,
                GEMINI_PROVIDER_ID: GEMINI_CONNECTION_ID,
            }.get(provider_id)
            if connection_id is None:
                raise ValueError("O provedor não possui conexão configurada nesta interface.")
            adapter_id = f"personal:{agent_id}"
        else:
            connection_id = None
            adapter_id = f"personal:{agent_id}"

        if agent_id in {item[0] for item in self.DEMO_AGENTS}:
            raise ValueError("O identificador é reservado para agente demonstrativo.")

        definition = AgentDefinition(
            id=agent_id,
            name=name,
            description=description,
            capabilities=capabilities,
            adapter_id=adapter_id,
        )
        registered = self.agents.register(definition)
        try:
            if self.settings_store is not None:
                self.settings_store.save_desktop_agent(
                    self._record_for_agent(registered),
                    binding_connection_id=connection_id,
                )
            if connection_id is not None:
                self.bindings.register(registered.id, connection_id)
        except Exception:
            self.agents.delete(registered.id)
            if self.settings_store is not None:
                self.settings_store.delete_desktop_agent(registered.id)
            raise
        self._personal_agent_ids.add(registered.id)
        return registered

    def set_agent_enabled(self, agent_id: str, enabled: bool) -> AgentDefinition:
        if not isinstance(enabled, bool):
            raise ValueError("enabled precisa ser booleano.")
        current = self.agents.get(agent_id)
        updated = replace(current, enabled=enabled)
        if agent_id in self._personal_agent_ids and self.settings_store is not None:
            self.settings_store.save_desktop_agent(self._record_for_agent(updated))
        return self.agents.update(updated)

    def update_agent(
        self,
        agent_id: str,
        *,
        name: str,
        description: str,
        capabilities: tuple[str, ...],
    ) -> AgentDefinition:
        if agent_id not in self._personal_agent_ids:
            raise ValueError("Somente agentes pessoais podem ser editados.")
        current = self.agents.get(agent_id)
        updated = AgentDefinition(
            id=current.id,
            name=name,
            description=description,
            capabilities=capabilities,
            adapter_id=current.adapter_id,
            enabled=current.enabled,
        )
        if self.settings_store is not None:
            self.settings_store.save_desktop_agent(self._record_for_agent(updated))
        return self.agents.update(updated)

    def delete_agent(self, agent_id: str) -> AgentDefinition:
        if agent_id not in self._personal_agent_ids:
            raise ValueError("Somente agentes pessoais podem ser excluídos.")
        current = self.agents.get(agent_id)
        if self.settings_store is not None:
            self.settings_store.delete_desktop_agent(agent_id)
        self.bindings.remove_for_agent(agent_id)
        deleted = self.agents.delete(agent_id)
        self._personal_agent_ids.remove(agent_id)
        return deleted

    def is_personal_agent(self, agent_id: str) -> bool:
        return agent_id in self._personal_agent_ids

    def bind_agent(self, agent_id: str, provider_id: str):
        self.agents.get(agent_id)
        self.providers.get(provider_id)
        connection_id = {
            CODEX_PROVIDER_ID: CODEX_CONNECTION_ID,
            GEMINI_PROVIDER_ID: GEMINI_CONNECTION_ID,
        }.get(provider_id)
        if connection_id is None:
            raise ValueError("O provedor não possui conexão configurada nesta interface.")
        binding = self.bindings.register(agent_id, connection_id)
        if agent_id in self._personal_agent_ids and self.settings_store is not None:
            try:
                self.settings_store.save_desktop_binding(
                    DesktopAgentBindingRecord(agent_id, connection_id)
                )
            except Exception:
                self.bindings.unregister(binding.id)
                raise
        return binding

    @staticmethod
    def _record_for_agent(agent: AgentDefinition) -> DesktopAgentRecord:
        return DesktopAgentRecord(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            capabilities=agent.capabilities,
            enabled=agent.enabled,
        )

    def diagnose_integrations(self):
        """Executa apenas probes locais; não consulta contas nem estabelece rede."""
        return self.diagnostics.diagnose()

    def begin_codex_login(
        self,
        method: CodexLoginMethod,
        authorization: AuthorizationContext,
    ) -> CodexLoginResult:
        PermissionPolicy.require(Permission.WEB_ACCESS, authorization)
        return self.codex_auth.start_login(method, authorization)

    def finish_codex_login(
        self,
        session_id: str,
        authorization: AuthorizationContext,
    ) -> CodexLoginCompletion:
        PermissionPolicy.require(Permission.WEB_ACCESS, authorization)
        login = self.codex_auth.finish_login(session_id, authorization)
        if login.state is not CodexLoginState.COMPLETED:
            return CodexLoginCompletion(login, None)
        connection = self._verify_codex_connection(authorization)
        account_state = {
            ConnectionStatus.CONNECTED: CodexAccountState.AUTHENTICATED,
            ConnectionStatus.CONNECTION_REQUIRED: CodexAccountState.NOT_AUTHENTICATED,
        }.get(connection.status, CodexAccountState.ERROR)
        return CodexLoginCompletion(login, account_state)

    def cancel_codex_login(
        self,
        session_id: str,
        authorization: AuthorizationContext,
    ) -> CodexLoginResult:
        PermissionPolicy.require(Permission.WEB_ACCESS, authorization)
        return self.codex_auth.cancel_login(session_id, authorization)

    def verify_codex_account(
        self,
        authorization: AuthorizationContext,
    ) -> CodexAccountState:
        PermissionPolicy.require(Permission.WEB_ACCESS, authorization)
        connection = self._verify_codex_connection(authorization)
        return {
            ConnectionStatus.CONNECTED: CodexAccountState.AUTHENTICATED,
            ConnectionStatus.CONNECTION_REQUIRED: CodexAccountState.NOT_AUTHENTICATED,
        }.get(connection.status, CodexAccountState.ERROR)

    def _verify_codex_connection(self, authorization: AuthorizationContext):
        verifiers = ConnectionVerifierRegistry()
        verifiers.register(
            CODEX_PROVIDER_ID,
            CodexConnectionVerifier(self.codex_auth, authorization),
        )
        return ConnectionService(self.connections, verifiers).verify(CODEX_CONNECTION_ID)

    def run_demo(self, prompt: str, authorization: AuthorizationContext) -> MultiAgentResult:
        PermissionPolicy.require(Permission.AGENT_EXECUTE, authorization)
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Informe um tema para a demonstração.")
        first_id, second_id, third_id = (item[0] for item in self.DEMO_AGENTS)
        plan = MultiAgentPlan(
            tasks=(
                AgentTask(agent_id=first_id, instruction=f"Planejar: {prompt}", id="demo-plan"),
                AgentTask(
                    agent_id=second_id,
                    instruction="Revisar o resultado anterior.",
                    id="demo-review",
                    dependencies=(TaskDependency("demo-plan"),),
                ),
                AgentTask(
                    agent_id=third_id,
                    instruction="Consolidar os resultados anteriores.",
                    id="demo-synthesis",
                    dependencies=(TaskDependency("demo-review"),),
                ),
            ),
            id="desktop-demonstration",
        )
        coordinator = MaestroCoordinator(self.agents, self.executors)
        return MultiAgentWorkflow(coordinator).execute(plan, authorization)
