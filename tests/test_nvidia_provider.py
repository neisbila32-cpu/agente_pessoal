import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from openai import APIConnectionError, APIStatusError, APITimeoutError

from agente_pessoal.ai import AIPlanner, ModelRequest, ModelResponse
from agente_pessoal.ai.errors import (
    MissingCredentialError,
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    PlanValidationError,
)
from agente_pessoal.ai.nvidia import NvidiaNimProvider
from agente_pessoal.config import Settings
from agente_pessoal.core import UserRequest
from agente_pessoal.core.executor import ToolExecutor
from agente_pessoal.security import AuthorizationContext, Permission, PermissionDenied
from agente_pessoal.tools import ToolDescription


def valid_plan() -> str:
    return json.dumps(
        {
            "interpretation": {
                "objective": "Concluir teste",
                "intent": "teste",
                "required_information": [],
                "limitations": [],
                "ambiguities": [],
                "requires_clarification": False,
            },
            "steps": [
                {"description": "Ação controlada", "tool_name": "controlled", "arguments": {}}
            ],
        }
    )


class FakeClient:
    def __init__(self, result=None, error=None):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=MagicMock(side_effect=error, return_value=result))
        )
        self.close = MagicMock()


class NvidiaProviderTests(unittest.TestCase):
    def setUp(self):
        self.request = ModelRequest(
            prompt="Gere JSON",
            model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            credential_env_var="NVIDIA_API_KEY",
            timeout_seconds=9.5,
            max_output_chars=1000,
        )

    def completion(self, content):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def test_sends_expected_model_messages_endpoint_timeout_and_no_sdk_retries(self):
        client = FakeClient(self.completion('{"ok":true}'))
        factory = MagicMock(return_value=client)
        provider = NvidiaNimProvider(factory)

        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key", "OPENAI_API_KEY": "other"}):
            response = provider.generate(self.request)

        self.assertEqual(response.content, '{"ok":true}')
        factory.assert_called_once_with(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="secret-key",
            timeout=9.5,
            max_retries=0,
        )
        client.chat.completions.create.assert_called_once_with(
            model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            messages=[{"role": "user", "content": "Gere JSON"}],
            temperature=0.2,
            max_tokens=4096,
            stream=False,
        )
        client.close.assert_called_once()

    def test_requires_only_nvidia_credential_and_does_not_leak_it(self):
        provider = NvidiaNimProvider(MagicMock())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-secret"}, clear=True):
            with self.assertRaises(MissingCredentialError) as raised:
                provider.generate(self.request)
        self.assertNotIn("openai-secret", str(raised.exception))

        request = ModelRequest("p", "m", "OTHER_KEY", 1.0, 100)
        with self.assertRaises(ModelProviderError):
            provider.generate(request)

    def test_rejects_malformed_empty_and_oversized_responses(self):
        provider = NvidiaNimProvider(lambda **_: FakeClient(self.completion(None)))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test"}):
            with self.assertRaises(ModelResponseError):
                provider.generate(self.request)
        provider = NvidiaNimProvider(lambda **_: FakeClient(SimpleNamespace(choices=[])))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test"}):
            with self.assertRaises(ModelResponseError):
                provider.generate(self.request)
        provider = NvidiaNimProvider(lambda **_: FakeClient(self.completion("x" * 1001)))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test"}):
            with self.assertRaises(ModelResponseError):
                provider.generate(self.request)

    def test_normalizes_timeout_and_connection_errors_without_raw_messages(self):
        request = MagicMock()
        for error, expected in (
            (APITimeoutError(request=request), ModelTimeoutError),
            (APIConnectionError(message="secret transport detail", request=request), ModelUnavailableError),
        ):
            provider = NvidiaNimProvider(lambda **_: FakeClient(error=error))
            with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key"}):
                with self.assertRaises(expected) as raised:
                    provider.generate(self.request)
            self.assertNotIn("secret", str(raised.exception).lower())

    def test_normalizes_api_status_errors_and_hides_response_body(self):
        response = MagicMock(status_code=503, request=MagicMock())
        error = APIStatusError("secret response body", response=response, body={"secret": "key"})
        provider = NvidiaNimProvider(lambda **_: FakeClient(error=error))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key"}):
            with self.assertRaises(ModelUnavailableError) as raised:
                provider.generate(self.request)
        self.assertIn("503", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception).lower())

        response.status_code = 401
        provider = NvidiaNimProvider(lambda **_: FakeClient(error=APIStatusError(
            "secret", response=response, body={"secret": "key"}
        )))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key"}):
            with self.assertRaises(ModelProviderError) as raised:
                provider.generate(self.request)
        self.assertIn("401", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception).lower())

    def test_provider_is_compatible_with_planner_and_cannot_grant_permissions(self):
        client = FakeClient(self.completion(valid_plan()))
        provider = NvidiaNimProvider(lambda **_: client)
        settings = Settings(ai_model=self.request.model, ai_max_attempts=1)
        planner = AIPlanner(
            provider,
            settings,
            [ToolDescription("controlled", "Ferramenta exclusivamente de teste")],
        )
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}):
            plan = planner.plan(UserRequest("Execute a ação controlada"))
        self.assertEqual(plan.steps[0].tool_name, "controlled")

        class ControlledTool:
            name = "controlled"
            required_permission = Permission.FILE_READ

            def execute(self, arguments):
                raise AssertionError("A ferramenta não autorizada não pode executar")

        tool = ControlledTool()
        executor = ToolExecutor([tool])
        with self.assertRaises(PermissionDenied):
            executor.execute(plan.steps[0], AuthorizationContext())


if __name__ == "__main__":
    unittest.main()
