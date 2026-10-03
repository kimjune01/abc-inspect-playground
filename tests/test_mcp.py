"""Exercise the real stdio MCP wire protocol, including decoded camera pixels."""

import base64
import io
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image


def metadata(result):
    assert not result.isError, result
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_mcp_images_actions_retries_and_native_log(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "abc_inspect.server", "--log-dir", str(tmp_path)],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        tools = await client.list_tools()
        assert {t.name for t in tools.tools} == {
            "start_trial",
            "observe",
            "move_joints",
            "jog_arm",
            "finish_trial",
        }
        started = await client.call_tool(
            "start_trial",
            {
                "request_id": "start-1",
                "seed": 7,
                "max_steps": 20,
            },
        )
        first = metadata(started)
        images = [block for block in started.content if block.type == "image"]
        assert len(images) == 3
        assert Image.open(io.BytesIO(base64.b64decode(images[0].data))).size == (224, 168)
        assert "object" not in first and "metrics" not in first
        session_id = first["session_id"]
        again = metadata(
            await client.call_tool(
                "start_trial",
                {
                    "request_id": "start-1",
                    "seed": 7,
                    "max_steps": 20,
                },
            )
        )
        assert again["session_id"] == session_id
        target = list(first["joint_pos"])
        target[0] += 0.05
        args = {
            "session_id": session_id,
            "request_id": "nudge",
            "expected_sequence": 0,
            "target": target,
            "steps": 5,
        }
        moved = metadata(await client.call_tool("move_joints", args))
        duplicate = metadata(await client.call_tool("move_joints", args))
        assert moved["physics_steps"] == duplicate["physics_steps"] == 5
        assert moved["sim_time"] > first["sim_time"]
        stale = await client.call_tool("move_joints", {**args, "request_id": "stale"})
        assert stale.isError
        ended = metadata(
            await client.call_tool(
                "finish_trial",
                {
                    "session_id": session_id,
                    "request_id": "finish",
                    "expected_sequence": 1,
                    "reason": "mcp_wire_test",
                },
            )
        )
        assert ended["physics_steps"] == 5
        log = json.loads(Path(ended["log_path"]).read_text())
        assert log["results"]["metrics"]["abc_success"] == 0.0
        assert "mcp_wire_test" in json.dumps(log)


@pytest.mark.asyncio
async def test_http_trial_survives_client_reconnect(tmp_path):
    import asyncio
    import socket

    import httpx

    from abc_inspect.client import call_tool

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "abc_inspect.server",
        "--transport",
        "streamable-http",
        "--port",
        str(port),
        "--log-dir",
        str(tmp_path / "logs"),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        async with httpx.AsyncClient() as http:
            for _ in range(100):
                try:
                    await http.get(url)
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.1)
            else:
                pytest.fail("HTTP server did not start")
        first = await call_tool(
            url, "start_trial", {"request_id": "start", "max_steps": 10}, tmp_path
        )
        # Every call_tool creates and closes its own HTTP MCP session.
        observed = await call_tool(url, "observe", {"session_id": first["session_id"]}, tmp_path)
        assert observed["status"] == "active", observed
        assert observed["physics_steps"] == 0
        moved = await call_tool(
            url,
            "move_joints",
            {
                "session_id": first["session_id"],
                "request_id": "move",
                "expected_sequence": 0,
                "target": first["joint_pos"],
                "steps": 2,
            },
            tmp_path,
        )
        assert moved["physics_steps"] == 2, moved
        end = await call_tool(
            url,
            "finish_trial",
            {
                "session_id": first["session_id"],
                "request_id": "finish",
                "expected_sequence": 1,
            },
            tmp_path,
        )
        assert end["status"] == "finished", end
    finally:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=15)
