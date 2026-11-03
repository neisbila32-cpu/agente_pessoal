"""CLI Windows para diagnóstico local e consulta Codex explicitamente autorizada."""

import argparse
from dataclasses import asdict
import json
import sys
from typing import Sequence, TextIO

from agente_pessoal.integrations.adapters import (
    CodexAuthService,
    GeminiCliAdapter,
    register_codex_provider,
    register_gemini_provider,
)
from agente_pessoal.integrations.diagnostics import (
    IntegrationDiagnostics,
    IntegrationDiagnosticReport,
)
from agente_pessoal.integrations.providers import ProviderRegistry
from agente_pessoal.security import AuthorizationContext, Permission


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agente-pessoal-diagnostico",
        description="Mostra o estado local das integrações Codex e Gemini CLI.",
    )
    parser.add_argument(
        "--verify-codex-account",
        action="store_true",
        help="consulta a conta Codex pelo SDK oficial (não executa prompts).",
    )
    parser.add_argument(
        "--allow-web-access",
        action="store_true",
        help="autoriza web.access somente para a consulta Codex desta execução.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emite o relatório estruturado em JSON.",
    )
    return parser


def _format_report(report: IntegrationDiagnosticReport) -> str:
    lines = ["Diagnóstico de integrações do Agente Pessoal"]
    for provider in report.providers:
        registration = "registrado" if provider.registered else "não registrado"
        lines.extend(
            [
                "",
                f"{provider.name} ({provider.provider_id}) — {registration}",
                f"  Autenticação: {provider.authentication_status.value}",
                f"  Operacional: {provider.operational_status.value}",
            ]
        )
        for dependency in provider.dependencies:
            version = f" ({dependency.version})" if dependency.version else ""
            lines.append(f"  Dependência {dependency.name}: {dependency.status.value}{version}")
        methods = ", ".join(provider.authentication_methods) or "nenhum declarado"
        lines.append(f"  Métodos de autenticação: {methods}")
        permissions = ", ".join(
            sorted({item.permission for item in provider.permissions})
        ) or "nenhuma para diagnóstico local"
        lines.append(f"  Permissões: {permissions}")
        if provider.unavailable_features:
            lines.append("  Indisponível: " + "; ".join(provider.unavailable_features))
        if provider.recommended_actions:
            lines.append("  Próximas ações:")
            lines.extend(f"    - {action}" for action in provider.recommended_actions)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None) -> int:
    args = _parser().parse_args(argv)
    output = stdout or sys.stdout
    providers = ProviderRegistry()
    register_codex_provider(providers)
    register_gemini_provider(providers)

    authorization = None
    if args.verify_codex_account and args.allow_web_access:
        # A concessão existe somente neste processo e apenas para a consulta pedida.
        authorization = AuthorizationContext.from_permissions((Permission.WEB_ACCESS,))

    report = IntegrationDiagnostics(
        providers,
        CodexAuthService(),
        GeminiCliAdapter(),
    ).diagnose(
        check_codex_account=args.verify_codex_account,
        authorization=authorization,
    )
    output.write(
        json.dumps(asdict(report), ensure_ascii=False, indent=2)
        if args.json
        else _format_report(report)
    )
    output.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
