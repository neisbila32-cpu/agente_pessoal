import unittest

from agente_pessoal.security import (
    AuthorizationContext,
    Permission,
    PermissionDenied,
    PermissionPolicy,
)


class PermissionPolicyTests(unittest.TestCase):
    def test_sensitive_permission_is_denied_without_context(self):
        with self.assertRaises(PermissionDenied):
            PermissionPolicy.require(Permission.COMMAND_EXECUTE)

    def test_ungranted_permission_is_denied(self):
        context = AuthorizationContext.from_permissions([Permission.FILE_READ])
        with self.assertRaises(PermissionDenied):
            PermissionPolicy.require(Permission.FILE_WRITE, context)

    def test_explicitly_granted_permission_is_allowed(self):
        context = AuthorizationContext.from_permissions([Permission.FILE_READ])
        PermissionPolicy.require(Permission.FILE_READ, context)


if __name__ == "__main__":
    unittest.main()
