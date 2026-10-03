"""Protocol client for TUI agents before MCP tools are loaded into their session."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call_tool(url: str, name: str, arguments: dict, output: Path) -> dict:
    started = time.monotonic()
    async with (
        streamable_http_client(url) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        result = await client.call_tool(name, arguments)
    if result.isError:
        return {"error": [block.model_dump() for block in result.content]}
    first = result.content[0]
    assert first.type == "text"
    metadata = json.loads(first.text)
    directory = output.resolve() / metadata["session_id"]
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    cameras = iter(metadata["camera_order"])
    for block in result.content:
        if block.type == "image":
            camera = next(cameras)
            path = directory / f"{metadata['sequence']:04d}-{camera}.png"
            path.write_bytes(base64.b64decode(block.data))
            files.append(str(path))
    metadata.update(image_files=files, rpc_wall_s=time.monotonic() - started)
    (directory / f"{metadata['sequence']:04d}-{name}.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8876/mcp")
    parser.add_argument("--output", type=Path, default=Path("outputs/client"))
    parser.add_argument("tool", choices=["start_trial", "observe", "move_joints", "finish_trial"])
    parser.add_argument("arguments", help="JSON object, or @path-to-json-file")
    args = parser.parse_args()
    raw = Path(args.arguments[1:]).read_text() if args.arguments.startswith("@") else args.arguments
    result = asyncio.run(call_tool(args.url, args.tool, json.loads(raw), args.output))
    print(json.dumps(result, indent=2))
    if "error" in result:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
