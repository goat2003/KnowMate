import json
import os
import threading
import unittest
from http.client import HTTPConnection
from memory_service import Handler, Repository, ThreadingHTTPServer


class MemoryServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["MEMORY_SERVICE_TOKEN"] = "test-token"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.backend = Repository(":memory:")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, payload, token="test-token"):
        conn = HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("POST", path, json.dumps(payload), {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    def get(self, path, token="test-token"):
        conn = HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("GET", path, headers={"Authorization": "Bearer " + token})
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    def test_isolation_and_auth(self):
        self.assertEqual(self.call("/memory/build", {"role_id": "km_" + "a" * 40, "dialogues": [{"user": "记住兴趣：Go"}]})[0], 200)
        status, data = self.call("/memory/list", {"role_id": "km_" + "b" * 40})
        self.assertEqual(status, 200)
        self.assertEqual(data["items"], [])
        self.assertEqual(self.call("/memory/list", {"role_id": "km_" + "a" * 40}, "wrong")[0], 401)
        self.assertEqual(self.call("/memory/delete", {"role_id": "km_" + "a" * 40})[0], 200)
        self.assertEqual(self.call("/memory/list", {"role_id": "km_" + "a" * 40})[1]["items"], [])

    def test_invalid_role_and_health_are_bounded(self):
        status, data = self.call("/memory/list", {"role_id": "user-a"})
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "invalid role_id")

        status, data = self.get("/health", "wrong")
        self.assertEqual(status, 401)
        self.assertNotIn("token", json.dumps(data).lower())

        status, data = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["memory"]["backend"], "local")
        self.assertNotIn("password", json.dumps(data["memory"]).lower())
        self.assertNotIn("token", json.dumps(data["memory"]).lower())


if __name__ == "__main__":
    unittest.main()
