from __future__ import annotations

import unittest

import grpc

from app.config import Settings
from app.grpc_server import AuthInterceptor, _metadata_authorized


class GrpcSecurityTest(unittest.TestCase):
    def test_missing_token_is_rejected_when_configured(self) -> None:
        self.assertFalse(_metadata_authorized((), "secret-token"))

    def test_bearer_or_api_key_token_is_accepted(self) -> None:
        self.assertTrue(_metadata_authorized((("authorization", "Bearer secret-token"),), "secret-token"))
        self.assertTrue(_metadata_authorized((("x-api-key", "secret-token"),), "secret-token"))

    def test_auth_interceptor_aborts_unauthorized_rpc(self) -> None:
        interceptor = AuthInterceptor(Settings(api_token="secret-token"))
        handler = interceptor.intercept_service(lambda _: None, _FakeHandlerCallDetails(()))

        self.assertIsNotNone(handler)
        with self.assertRaises(grpc.RpcError) as raised:
            handler.unary_unary(object(), _FakeContext())
        self.assertEqual(raised.exception.code(), grpc.StatusCode.UNAUTHENTICATED)


class _FakeHandlerCallDetails:
    method = "/agent.AgentService/HealthCheck"

    def __init__(self, metadata) -> None:
        self.invocation_metadata = metadata


class _FakeContext:
    def abort(self, code, details):
        raise _Aborted(code, details)


class _Aborted(grpc.RpcError):
    def __init__(self, code, details) -> None:
        super().__init__()
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


if __name__ == "__main__":
    unittest.main()
