from dataclasses import fields
from io import StringIO
import json
import unittest
from unittest.mock import patch

from agente_pessoal.integrations import (
    AuthenticationMethod,
    AuthenticationStatus,
    DependencyDiagnostic,
    DependencyStatus,
    IntegrationDiagnostics,
    OperationalStatus,
    PermissionRequirement,
    ProviderDiagnostic,
    ProviderRegistry,
)
from agente_pessoal.integrations.adapters import (
    CodexAccountCheck,
    CodexAccountState,
    CodexAuthService,
    GeminiCliAdapter,
    GeminiCliAvailability,
    register_codex_provider,
    register_gemini_provider,
)
from agente_pessoal.integrations.diagnostics_cli import main
from agente_pessoal.security import AuthorizationContext, Permission


WEB_AUTH = AuthorizationContext.from_permissions((Permission.WEB_ACCESS,))


class FakeCodexAuth:
    def __init__(self, state=CodexAccountState.AUTHENTICATED, available=True, error=None):
        self.state = state
        self.available = available
        self.error = error
        self.calls = 0

    def is_available(self):
        return self.available

    def check_account(self, authorization=None):
        self.calls += 1
        if self.error:
            raise self.error
        return CodexAccountCheck(self.state)


class FakeGeminiCli:
    def __init__(self, availability=GeminiCliAvailability.INSTALLED):
        self.state = availability
        self.calls = 0

    def availability(self):
        self.calls += 1
        return self.state


def make_diagnostics(
    *,
    registered=True,
    codex=None,
    gemini=None,
    version="0.163.0",
    runtime_version="0.163.0",
    runtime=True,
):
    providers = ProviderRegistry()
    if registered:
        register_codex_provider(providers)
        register_gemini_provider(providers)
    return IntegrationDiagnostics(
        providers,
        codex or FakeCodexAuth(),
        gemini or FakeGeminiCli(),
        codex_version_lookup=lambda: version,
        codex_runtime_version_lookup=lambda: runtime_version,
        codex_runtime_probe=lambda: runtime,
    )


class IntegrationDiagnosticsTests(unittest.TestCase):
    def test_reports_registered_providers_and_installed_dependencies_without_auth_checks(self):
        codex = FakeCodexAuth()
        gemini = FakeGeminiCli()

        report = make_diagnostics(codex=codex, gemini=gemini).diagnose()

        codex_report, gemini_report = report.providers
        self.assertTrue(codex_report.registered)
        self.assertEqual(codex_report.dependencies[0].status, DependencyStatus.INSTALLED)
        self.assertEqual(codex_report.dependencies[1].status, DependencyStatus.INSTALLED)
        self.assertEqual(codex_report.authentication_status, AuthenticationStatus.NOT_CHECKED)
        self.assertEqual(gemini_report.dependencies[0].status, DependencyStatus.INSTALLED)
        self.assertEqual(gemini_report.authentication_status, AuthenticationStatus.NOT_VERIFIED)
        self.assertEqual(codex.calls, 0)

    def test_reports_absent_providers_and_dependencies(self):
        report = make_diagnostics(
            registered=False,
            codex=FakeCodexAuth(available=False),
            gemini=FakeGeminiCli(GeminiCliAvailability.NOT_INSTALLED),
            version=None,
            runtime=False,
        ).diagnose()

        codex_report, gemini_report = report.providers
        self.assertFalse(codex_report.registered)
        self.assertEqual(codex_report.dependencies[0].status, DependencyStatus.MISSING)
        self.assertEqual(codex_report.dependencies[1].status, DependencyStatus.MISSING)
        self.assertFalse(gemini_report.registered)
        self.assertEqual(gemini_report.dependencies[0].status, DependencyStatus.MISSING)

    def test_reports_incompatible_codex_sdk_version_and_skips_auth_check(self):
        auth = FakeCodexAuth()
        report = make_diagnostics(codex=auth, version="0.162.9").diagnose(
            check_codex_account=True,
            authorization=WEB_AUTH,
        )
        codex = report.providers[0]

        self.assertEqual(codex.dependencies[0].status, DependencyStatus.INCOMPATIBLE)
        self.assertEqual(codex.dependencies[0].version, "0.162.9")
        self.assertEqual(codex.authentication_status, AuthenticationStatus.NOT_CHECKED)
        self.assertEqual(auth.calls, 0)

    def test_reports_runtime_version_mismatch(self):
        report = make_diagnostics(runtime_version="0.162.9").diagnose()

        self.assertEqual(report.providers[0].dependencies[1].status, DependencyStatus.INCOMPATIBLE)
        self.assertEqual(report.providers[0].dependencies[1].version, "0.162.9")

    def test_codex_account_check_runs_only_when_requested_authorized_and_compatible(self):
        auth = FakeCodexAuth(CodexAccountState.AUTHENTICATED)
        report = make_diagnostics(codex=auth).diagnose(
            check_codex_account=True,
            authorization=WEB_AUTH,
        )

        self.assertEqual(report.providers[0].authentication_status, AuthenticationStatus.AUTHENTICATED)
        self.assertEqual(auth.calls, 1)
        self.assertEqual(report.providers[0].operational_status, OperationalStatus.NOT_IMPLEMENTED)

    def test_codex_not_authenticated_and_error_states_are_distinct(self):
        not_authenticated = make_diagnostics(
            codex=FakeCodexAuth(CodexAccountState.NOT_AUTHENTICATED)
        ).diagnose(check_codex_account=True, authorization=WEB_AUTH)
        failed = make_diagnostics(
            codex=FakeCodexAuth(error=RuntimeError("private-token-value"))
        ).diagnose(check_codex_account=True, authorization=WEB_AUTH)

        self.assertEqual(
            not_authenticated.providers[0].authentication_status,
            AuthenticationStatus.NOT_AUTHENTICATED,
        )
        self.assertEqual(failed.providers[0].authentication_status, AuthenticationStatus.ERROR)
        self.assertNotIn("private-token-value", repr(failed))

    def test_missing_web_access_reports_permission_required_without_calling_codex(self):
        auth = FakeCodexAuth()

        report = make_diagnostics(codex=auth).diagnose(check_codex_account=True)

        self.assertEqual(
            report.providers[0].authentication_status,
            AuthenticationStatus.PERMISSION_REQUIRED,
        )
        self.assertEqual(auth.calls, 0)
        self.assertTrue(report.providers[0].permissions[0].required_for_current_check)

    def test_probe_failure_is_reported_as_unknown_without_exposing_details(self):
        def broken_probe():
            raise RuntimeError("secret-path-and-token")

        report = IntegrationDiagnostics(
            ProviderRegistry(),
            FakeCodexAuth(),
            FakeGeminiCli(),
            codex_version_lookup=broken_probe,
            codex_runtime_version_lookup=broken_probe,
            codex_runtime_probe=broken_probe,
        ).diagnose()

        self.assertEqual(report.providers[0].dependencies[0].status, DependencyStatus.UNKNOWN)
        self.assertEqual(report.providers[0].dependencies[1].status, DependencyStatus.UNKNOWN)
        self.assertNotIn("secret-path-and-token", repr(report))

    def test_gemini_installation_never_implies_authentication_or_operation(self):
        report = make_diagnostics(gemini=FakeGeminiCli()).diagnose()
        gemini = report.providers[1]

        self.assertEqual(gemini.authentication_status, AuthenticationStatus.NOT_VERIFIED)
        self.assertEqual(gemini.operational_status, OperationalStatus.NOT_IMPLEMENTED)
        self.assertEqual(gemini.dependencies[0].status, DependencyStatus.INSTALLED)

    def test_diagnostic_models_do_not_contain_credential_fields(self):
        forbidden = {"credential", "password", "token", "secret", "api_key"}
        for model in (DependencyDiagnostic, PermissionRequirement, ProviderDiagnostic):
            self.assertTrue({field.name for field in fields(model)}.isdisjoint(forbidden))
        self.assertNotIn("secret-token-value", repr(make_diagnostics().diagnose()))

    def test_cli_default_does_not_query_accounts_and_emits_structured_json(self):
        fake_auth = FakeCodexAuth()
        output = StringIO()
        with patch("agente_pessoal.integrations.diagnostics_cli.CodexAuthService", return_value=fake_auth), patch(
            "agente_pessoal.integrations.diagnostics_cli.GeminiCliAdapter",
            return_value=FakeGeminiCli(),
        ):
            result = main(["--json"], stdout=output)

        data = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(fake_auth.calls, 0)
        self.assertEqual(len(data["providers"]), 2)

    def test_cli_requires_both_explicit_codex_check_and_one_run_web_consent(self):
        fake_auth = FakeCodexAuth()
        output_without_consent = StringIO()
        output_with_consent = StringIO()
        with patch("agente_pessoal.integrations.diagnostics_cli.CodexAuthService", return_value=fake_auth), patch(
            "agente_pessoal.integrations.diagnostics_cli.GeminiCliAdapter",
            return_value=FakeGeminiCli(),
        ):
            main(["--verify-codex-account", "--json"], stdout=output_without_consent)
            denied = json.loads(output_without_consent.getvalue())
            main(
                ["--verify-codex-account", "--allow-web-access", "--json"],
                stdout=output_with_consent,
            )
            authorized = json.loads(output_with_consent.getvalue())

        self.assertEqual(fake_auth.calls, 1)
        self.assertEqual(
            denied["providers"][0]["authentication_status"],
            AuthenticationStatus.PERMISSION_REQUIRED.value,
        )
        self.assertEqual(
            authorized["providers"][0]["authentication_status"],
            AuthenticationStatus.AUTHENTICATED.value,
        )


if __name__ == "__main__":
    unittest.main()
