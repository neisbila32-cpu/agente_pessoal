"""Estado de apresentação e ações da interface, sem dependência de Tkinter."""

from dataclasses import dataclass
from enum import StrEnum

from agente_pessoal.desktop.services import DesktopApplicationServices
from agente_pessoal.security import AuthorizationContext, Permission


class DesktopPage(StrEnum):
    HOME = "home"
    INTEGRATIONS = "integrations"
    AGENTS = "agents"
    MAESTRO = "maestro"
    DIAGNOSTICS = "diagnostics"


@dataclass(frozen=True, slots=True)
class ProviderStatusRow:
    provider_id: str
    name: str
    installation: str
    authentication: str
    operation: str
    guidance: str


class DesktopController:
    """Controla navegação e encaminha ações à camada de serviços."""

    PAGES = (
        DesktopPage.HOME,
        DesktopPage.INTEGRATIONS,
        DesktopPage.AGENTS,
        DesktopPage.MAESTRO,
        DesktopPage.DIAGNOSTICS,
    )

    def __init__(self, services: DesktopApplicationServices | None = None) -> None:
        self.services = services or DesktopApplicationServices()
        self.current_page = DesktopPage.HOME
        self._codex_login_id: str | None = None
        self._codex_login_authorization = None
        self._codex_authentication = "Não verificada"

    def navigate(self, page: DesktopPage | str) -> DesktopPage:
        try:
            selected = page if isinstance(page, DesktopPage) else DesktopPage(page)
        except ValueError:
            raise ValueError("Tela desconhecida.") from None
        self.current_page = selected
        return selected

    @property
    def codex_authentication(self) -> str:
        return self._codex_authentication

    @property
    def codex_login_active(self) -> bool:
        return self._codex_login_id is not None

    def integration_statuses(self) -> tuple[ProviderStatusRow, ...]:
        report = self.services.diagnose_integrations()
        rows = []
        for provider in report.providers:
            if provider.provider_id == "google-gemini-cli":
                authentication = "Não verificada"
            elif provider.provider_id == "openai-codex":
                authentication = self._codex_authentication
            else:
                authentication = "Não verificada"
            statuses = {dependency.status.value for dependency in provider.dependencies}
            if not statuses:
                installation = "Não aplicável"
            elif statuses == {"installed"}:
                installation = "Instalada"
            elif "incompatible" in statuses:
                installation = "Incompatível"
            elif "missing" in statuses:
                installation = "Ausente"
            else:
                installation = "Não verificada"
            rows.append(
                ProviderStatusRow(
                    provider_id=provider.provider_id,
                    name=provider.name,
                    installation=installation,
                    authentication=authentication,
                    operation=(
                        "Não disponível — execução real desativada"
                        if provider.operational_status.value == "not_implemented"
                        else provider.operational_status.value
                    ),
                    guidance=" ".join(provider.recommended_actions),
                )
            )
        return tuple(rows)

    def start_codex_login(self, method, *, confirmed: bool):
        if self.codex_login_active:
            raise ValueError("Já existe um login Codex em andamento.")
        authorization = self._one_run_web_authorization(confirmed)
        result = self.services.begin_codex_login(method, authorization)
        self._codex_login_id = result.session_id
        self._codex_login_authorization = authorization
        return result

    def finish_codex_login(self):
        if not self._codex_login_id or self._codex_login_authorization is None:
            raise ValueError("Não há login Codex em andamento.")
        result = self.services.finish_codex_login(
            self._codex_login_id,
            self._codex_login_authorization,
        )
        if result.account_state is not None:
            self._codex_authentication = {
                "authenticated": "Autenticada (verificada)",
                "not_authenticated": "Não autenticada (verificada)",
                "error": "Erro de verificação",
            }[result.account_state.value]
        if result.login.state.value != "pending":
            self._clear_login()
        return result

    def cancel_codex_login(self):
        if not self._codex_login_id or self._codex_login_authorization is None:
            raise ValueError("Não há login Codex em andamento.")
        result = self.services.cancel_codex_login(
            self._codex_login_id,
            self._codex_login_authorization,
        )
        self._clear_login()
        return result

    def verify_codex_account(self, *, confirmed: bool):
        authorization = self._one_run_web_authorization(confirmed)
        state = self.services.verify_codex_account(authorization)
        self._codex_authentication = {
            "authenticated": "Autenticada (verificada)",
            "not_authenticated": "Não autenticada (verificada)",
            "error": "Erro de verificação",
        }[state.value]
        return state

    def add_agent(
        self,
        *,
        agent_id: str,
        name: str,
        description: str,
        capabilities_text: str,
        provider_id: str | None = None,
    ):
        capabilities = tuple(item.strip() for item in capabilities_text.split(",") if item.strip())
        if not capabilities:
            raise ValueError("Informe ao menos uma capacidade.")
        return self.services.register_agent(
            agent_id=agent_id.strip(),
            name=name.strip(),
            description=description.strip(),
            capabilities=capabilities,
            provider_id=provider_id or None,
        )

    def set_agent_enabled(self, agent_id: str, enabled: bool):
        return self.services.set_agent_enabled(agent_id, enabled)

    def update_agent(self, agent_id: str, *, name: str, description: str, capabilities_text: str):
        capabilities = tuple(item.strip() for item in capabilities_text.split(",") if item.strip())
        if not capabilities:
            raise ValueError("Informe ao menos uma capacidade.")
        return self.services.update_agent(
            agent_id,
            name=name.strip(),
            description=description.strip(),
            capabilities=capabilities,
        )

    def delete_agent(self, agent_id: str):
        return self.services.delete_agent(agent_id)

    def is_personal_agent(self, agent_id: str) -> bool:
        return self.services.is_personal_agent(agent_id)

    def bind_agent(self, agent_id: str, provider_id: str):
        return self.services.bind_agent(agent_id, provider_id)

    def run_demo(self, prompt: str, *, confirmed: bool):
        if not confirmed:
            raise PermissionError("A demonstração requer confirmação explícita.")
        authorization = AuthorizationContext.from_permissions((Permission.AGENT_EXECUTE,))
        return self.services.run_demo(prompt, authorization)

    @staticmethod
    def _one_run_web_authorization(confirmed: bool) -> AuthorizationContext:
        if not confirmed:
            raise PermissionError("A operação requer autorização explícita para web.access.")
        return AuthorizationContext.from_permissions((Permission.WEB_ACCESS,))

    def _clear_login(self) -> None:
        self._codex_login_id = None
        self._codex_login_authorization = None
