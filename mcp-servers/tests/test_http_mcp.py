from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from urllib.error import HTTPError
from urllib import request as urlrequest
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class HttpMcpServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        env = dict(os.environ)
        env.update(
            {
                "PORT": str(cls.port),
                "MCP_TRANSPORT": "streamable_http",
                "EMBEDDING_MOCK_MODE": "true",
            }
        )
        cls.process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=ROOT / "mcp-servers" / "embedding-mcp",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                urlrequest.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("embedding-mcp did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.process.terminate()
        cls.process.wait(timeout=10)

    def test_official_streamable_http_lists_and_calls_tools(self) -> None:
        async def exercise() -> None:
            async with streamable_http_client(f"http://127.0.0.1:{self.port}/mcp") as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool("embed_text", {"text": "hello"})

            self.assertIn("embed_text", [tool.name for tool in tools.tools])
            self.assertFalse(result.isError)
            self.assertEqual(result.structuredContent["dim"], 8)

        asyncio.run(exercise())

    def test_official_server_validates_tool_input_schema(self) -> None:
        async def exercise() -> None:
            async with streamable_http_client(f"http://127.0.0.1:{self.port}/mcp") as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("embed_text", {"text": 42})

            self.assertTrue(result.isError)
            self.assertIn("Input validation error", result.content[0].text)

        asyncio.run(exercise())

    def test_unavailable_real_provider_stays_alive_and_reports_unhealthy(self) -> None:
        port = _free_port()
        env = dict(os.environ)
        env.update(
            {
                "PORT": str(port),
                "MCP_TRANSPORT": "streamable_http",
                "EMBEDDING_PROVIDER": "openai",
                "OPENAI_API_KEY": "",
            }
        )
        process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=ROOT / "mcp-servers" / "embedding-mcp",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 15
            health = None
            while time.time() < deadline:
                try:
                    urlrequest.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read()
                except HTTPError as exc:
                    if exc.code == 503:
                        health = json.loads(exc.read())
                        break
                except OSError:
                    time.sleep(0.1)
            self.assertIsNotNone(health)
            self.assertEqual(health["status"], "unhealthy")
            self.assertIsNone(process.poll())

            async def exercise() -> None:
                async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool("embed_text", {"text": "hello"})
                self.assertTrue(result.isError)
                self.assertIn("OPENAI_API_KEY", result.content[0].text)

            asyncio.run(exercise())
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
