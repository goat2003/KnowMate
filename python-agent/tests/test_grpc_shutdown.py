from __future__ import annotations

import unittest

from app.grpc_server import stop_grpc_server


class GrpcShutdownTest(unittest.TestCase):
    def test_stop_grpc_server_stops_with_grace_and_closes_service(self) -> None:
        server = _FakeServer()
        service = _FakeService()

        stop_grpc_server(server, service, grace_seconds=7)

        self.assertEqual(server.stop_calls, [7])
        self.assertTrue(server.future.waited)
        self.assertTrue(service.closed)


class _FakeStopFuture:
    def __init__(self) -> None:
        self.waited = False

    def wait(self, timeout=None):
        self.waited = True
        return True


class _FakeServer:
    def __init__(self) -> None:
        self.stop_calls: list[int] = []
        self.future = _FakeStopFuture()

    def stop(self, grace):
        self.stop_calls.append(grace)
        return self.future


class _FakeService:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


if __name__ == "__main__":
    unittest.main()
