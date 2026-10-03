"""Small localhost/stdio MCP surface; all physics belongs to Inspect's worker."""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from PIL import Image

from abc_inspect.adapter import TASK
from abc_inspect.session import Session


def content(observation: dict) -> list[TextContent | ImageContent]:
    metadata = {k: v for k, v in observation.items() if k != "images"}
    metadata["camera_order"] = list(observation["images"])
    result: list[TextContent | ImageContent] = [TextContent(type="text", text=json.dumps(metadata))]
    for name, pixels in observation["images"].items():
        buffer = io.BytesIO()
        Image.fromarray(pixels).save(buffer, format="PNG")
        result.extend(
            [
                TextContent(type="text", text=f"Camera: {name}"),
                ImageContent(
                    type="image",
                    mimeType="image/png",
                    data=base64.b64encode(buffer.getvalue()).decode(),
                ),
            ]
        )
    return result


def create_server(log_dir: Path, port: int = 8876):
    sessions: dict[str, Session] = {}
    starts: dict[str, tuple[int, int, str, str]] = {}
    start_lock = asyncio.Lock()

    mcp = FastMCP(
        "ABC Inspect prototype",
        host="127.0.0.1",
        port=port,
        instructions=(
            "Local simulation only. One active trial. Camera RGB + 14 joint values; "
            "left 6 radians + gripper, right 6 radians + gripper; gripper 0 closed, 1 open. "
            "Time is paused between commands. Reuse EXACT request_id and arguments after "
            "a timeout. New actions require the latest sequence; old retry results can be stale. "
            "finish_trial records completion, not task success. No world editing or oracle during play."
        ),
    )

    def lookup(session_id: str):
        if session_id not in sessions:
            raise ValueError("Unknown session_id; server restarts invalidate sessions")
        return sessions[session_id]

    @mcp.tool()
    async def start_trial(
        request_id: str, seed: int = 7, max_steps: int = 300, task: str = TASK
    ) -> list[TextContent | ImageContent]:
        """Start an ABC task (count_one/two/three_into_opaque_box, spell_cat/dog/fish, count_into_opaque_box, or put_plastic_bottles_in_bin); returns session_id, sequence, proprioception and three PNGs.

        A duplicate start returns the same session's latest state, or an archived error.
        Keep 8 recent trials, up to 256 starts per server lifetime; one active at a time. max_steps 1..1000, idle timeout 15 minutes.
        """
        async with start_lock:
            if request_id in starts:
                previous_seed, previous_steps, previous_task, session_id = starts[request_id]
                if (seed, max_steps, task) != (previous_seed, previous_steps, previous_task):
                    raise ValueError("request_id reused with a different start payload")
                if session_id not in sessions:
                    raise ValueError("Trial archived; use a new request_id for a new trial")
                return content(await asyncio.to_thread(sessions[session_id].observe))
            if not request_id or len(request_id) > 128:
                raise ValueError("request_id must contain 1 to 128 characters")
            if len(starts) >= 256:
                raise ValueError("Prototype trial limit reached; restart server after 256 trials")
            if any(s.current["status"] != "finished" and not s.closed for s in sessions.values()):
                raise ValueError("Finish the active trial before starting another")
            if len(sessions) >= 8:
                oldest_id = next(iter(sessions))
                await asyncio.to_thread(sessions[oldest_id].close)
                del sessions[oldest_id]
            session = await asyncio.to_thread(
                Session, log_dir, seed=seed, max_steps=max_steps, task=task
            )
            sessions[session.id] = session
            starts[request_id] = (seed, max_steps, task, session.id)
            return content(await asyncio.to_thread(session.observe))

    @mcp.tool()
    async def observe(session_id: str) -> list[TextContent | ImageContent]:
        """Read latest completed state and actual camera PNGs without advancing simulation."""
        return content(await asyncio.to_thread(lookup(session_id).observe))

    @mcp.tool()
    async def move_joints(
        session_id: str,
        request_id: str,
        expected_sequence: int,
        target: list[float],
        steps: int = 5,
    ) -> list[TextContent | ImageContent]:
        """Apply 14 absolute actuator targets through real dynamics for 1..30 control ticks.

        Each arm joint may change at most 0.2 radians from observed state; grippers
        at most 0.25. Bounds are returned by observe. Duplicate requests never move twice.
        Calls serialize; competing commands with an old sequence are rejected.
        """
        result = await asyncio.to_thread(
            lookup(session_id).move, request_id, expected_sequence, target, steps=steps
        )
        return content(result)

    @mcp.tool()
    async def jog_arm(
        session_id: str,
        request_id: str,
        expected_sequence: int,
        translation: list[float],
        yaw: float = 0.0,
        gripper: float | None = None,
        arm: str = "left",
        steps: int = 5,
    ) -> list[TextContent | ImageContent]:
        """Jog grasp site in world metres and world-Z yaw radians using robot-only IK.

        Translation norm <= .026m, yaw <= .12rad. Gripper 0 closes, 1 opens.
        Real bounded actuator motion; obstacles and reach limits can prevent movement.
        """
        result = await asyncio.to_thread(
            lookup(session_id).jog,
            request_id,
            expected_sequence,
            translation=translation,
            yaw=yaw,
            gripper=gripper,
            arm=arm,
            steps=steps,
        )
        return content(result)

    @mcp.tool()
    async def finish_trial(
        session_id: str, request_id: str, expected_sequence: int, reason: str = "agent_finished"
    ) -> list[TextContent | ImageContent]:
        """Finish without advancing physics; return native Inspect JSON path and final metrics.

        The simulator oracle scores task success independently of the reason string.
        Inspect eval_status='success' only means the evaluation completed without errors.
        """
        result = await asyncio.to_thread(
            lookup(session_id).finish, request_id, expected_sequence, reason=reason
        )
        return content(result)

    from abc_inspect.play import add_play_routes

    add_play_routes(mcp, port)
    return mcp, sessions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--log-dir", type=Path, default=Path("outputs/trials"))
    args = parser.parse_args()
    server, sessions = create_server(args.log_dir.resolve(), args.port)
    if args.transport == "streamable-http":
        import uvicorn

        app = server.streamable_http_app()
        transport_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def app_lifespan(app):
            async with transport_lifespan(app):
                try:
                    yield
                finally:
                    for session in sessions.values():
                        await asyncio.to_thread(session.close)

        # HTTP connections may come and go; robot sessions live until server shutdown.
        app.router.lifespan_context = app_lifespan
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    else:
        try:
            server.run(transport="stdio")
        finally:
            for session in sessions.values():
                session.close()


if __name__ == "__main__":
    main()
