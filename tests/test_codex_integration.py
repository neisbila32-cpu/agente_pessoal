from dataclasses import fields
from types import SimpleNamespace
import unittest

from agente_pessoal.integrations import (
    AuthenticationMethod,
    ConnectionRegistry,
    ConnectionService,
    ConnectionStatus,
    ConnectionVerificationStatus,
    ConnectionVerifierRegistry,
    ProviderAvailability,
    ProviderConnection,
    ProviderRegistry,
)
from agente_pessoal.integrations.adapters.codex import (
    CODEX_PROVIDER_ID,
    CodexAccountState,
    CodexAuthError,
    CodexAuthService,
    CodexConnectionVerifier,
    CodexLoginMethod,
    CodexLoginState,
    CodexProviderUnavailableError,
    register_codex_provider,
)
from agente_pessoal.security import AuthorizationContext, Permission, PermissionDenied


AUTH = AuthorizationContext.from_permissions((Permission.WEB_ACCESS,))


class FakeHandle:
    auth_url = "https://auth.example.test/login"
    verification_url = "https://auth.example.test/device"
    user_code = "ABCD-EFGH"

    def __init__(self, success=True):
        self.success = success
        self.cancelled = False

    def wait(self):
        return SimpleNamespace(success=self.success)

    def cancel(self):
        self.cancelled = True


class FakeCodex:
    def __init__(self, account=object(), login_success=True):
        self.account_value = account
        self.login_success = login_success
        self.closed = False
        self.handle = FakeHandle(login_success)

    def account(self):
        return SimpleNamespace(account=self.account_value)

    def login_chatgpt(self):
        return self.handle

    def login_chatgpt_device_code(self):
        return self.handle

    def close(self):
        self.closed = True


class CodexIntegrationTests(unittest.TestCase):
    def test_provider_registration_is_explicit_and_isolated(self):
        providers = ProviderRegistry()
        provider = register_codex_provider(providers)
        self.assertEqual(provider.id, CODEX_PROVIDER_ID)
        self.assertEqual(providers.list_providers(), (provider,))
        self.assertEqual(
            provider.authentication_methods,
            (AuthenticationMethod.BROWSER_LOGIN, AuthenticationMethod.DEVICE_CODE_LOGIN),
        )

    def test_sdk_and_runtime_unavailable(self):
        service = CodexAuthService(availability_probe=lambda: False)
        self.assertFalse(service.is_available())
        with self.assertRaises(CodexProviderUnavailableError):
            service.check_account(AUTH)

    def test_every_remote_operation_requires_web_access(self):
        created = []

        def factory():
            created.append(True)
            return FakeCodex()

        service = CodexAuthService(factory, availability_probe=lambda: True)
        with self.assertRaises(PermissionDenied):
            service.start_login(CodexLoginMethod.BROWSER)
        with self.assertRaises(PermissionDenied):
            service.check_account()
        self.assertEqual(created, [])

    def test_installed_sdk_and_runtime_are_detected_without_starting_codex(self):
        service = CodexAuthService()
        self.assertTrue(service.is_available())

    def test_account_status_is_sanitized(self):
        for account, expected in (
            (object(), CodexAccountState.AUTHENTICATED),
            (None, CodexAccountState.NOT_AUTHENTICATED),
        ):
            service = CodexAuthService(
                lambda value=account: FakeCodex(account=value),
                availability_probe=lambda: True,
            )
            self.assertEqual(service.check_account(AUTH).state, expected)

    def test_account_failure_does_not_expose_exception(self):
        class Broken(FakeCodex):
            def account(self):
                raise RuntimeError("secret-token-value")

        service = CodexAuthService(lambda: Broken(), availability_probe=lambda: True)
        result = service.check_account(AUTH)
        self.assertEqual(result.state, CodexAccountState.ERROR)
        self.assertNotIn("secret-token-value", repr(result))

    def test_browser_and_device_login_can_finish_or_cancel(self):
        clients = []

        def factory():
            client = FakeCodex()
            clients.append(client)
            return client

        service = CodexAuthService(factory, availability_probe=lambda: True)
        browser = service.start_login(CodexLoginMethod.BROWSER, AUTH)
        self.assertEqual(browser.state, CodexLoginState.PENDING)
        self.assertEqual(browser.verification_url, "https://auth.example.test/login")
        self.assertEqual(service.finish_login(browser.session_id, AUTH).state, CodexLoginState.COMPLETED)
        self.assertTrue(clients[-1].closed)

        device = service.start_login(CodexLoginMethod.DEVICE_CODE, AUTH)
        self.assertEqual(device.user_code, "ABCD-EFGH")
        self.assertEqual(service.cancel_login(device.session_id, AUTH).state, CodexLoginState.CANCELLED)
        self.assertTrue(clients[-1].handle.cancelled)
        self.assertTrue(clients[-1].closed)
        with self.assertRaises(CodexAuthError):
            service.finish_login(device.session_id, AUTH)

    def test_failed_login_is_explicit_and_sanitized(self):
        service = CodexAuthService(
            lambda: FakeCodex(login_success=False), availability_probe=lambda: True
        )
        login = service.start_login(CodexLoginMethod.DEVICE_CODE, AUTH)
        result = service.finish_login(login.session_id, AUTH)
        self.assertEqual(result.state, CodexLoginState.FAILED)
        self.assertNotIn("account", repr(result))

    def test_connection_only_becomes_connected_after_positive_account_check(self):
        providers = ProviderRegistry()
        provider = register_codex_provider(providers)
        connections = ConnectionRegistry(providers)
        connection = ProviderConnection(
            provider.id,
            AuthenticationMethod.BROWSER_LOGIN,
        )
        connections.register(connection)
        verifier_registry = ConnectionVerifierRegistry()

        unauthenticated = CodexAuthService(
            lambda: FakeCodex(account=None), availability_probe=lambda: True
        )
        verifier_registry.register(provider.id, CodexConnectionVerifier(unauthenticated, AUTH))
        service = ConnectionService(connections, verifier_registry)
        pending = service.verify(connection.id)
        self.assertEqual(pending.status, ConnectionStatus.CONNECTION_REQUIRED)
        self.assertEqual(pending.verification_status, ConnectionVerificationStatus.VERIFIED)

        verifier_registry = ConnectionVerifierRegistry()
        authenticated = CodexAuthService(lambda: FakeCodex(), availability_probe=lambda: True)
        verifier_registry.register(provider.id, CodexConnectionVerifier(authenticated, AUTH))
        connected = ConnectionService(connections, verifier_registry).verify(connection.id)
        self.assertEqual(connected.status, ConnectionStatus.CONNECTED)
        self.assertEqual(connected.availability, ProviderAvailability.AVAILABLE)

    def test_verifier_without_web_authorization_fails_closed(self):
        providers = ProviderRegistry()
        provider = register_codex_provider(providers)
        connection = ProviderConnection(provider.id, AuthenticationMethod.DEVICE_CODE_LOGIN)
        verifier = CodexConnectionVerifier(
            CodexAuthService(lambda: FakeCodex(), availability_probe=lambda: True)
        )
        result = verifier.verify(connection, provider)
        self.assertEqual(result.status, ConnectionStatus.ERROR)
        self.assertEqual(result.availability, ProviderAvailability.UNKNOWN)

    def test_public_models_do_not_expose_credential_fields_and_no_executor_is_added(self):
        forbidden = {"credential", "password", "token", "secret", "api_key"}
        self.assertTrue({field.name for field in fields(ProviderConnection)}.isdisjoint(forbidden))
        self.assertFalse(hasattr(CodexAuthService, "execute"))


if __name__ == "__main__":
    unittest.main()
