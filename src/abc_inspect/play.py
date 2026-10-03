"""Same-origin browser controls over the same tools available to agents."""

import json
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response


def add_play_routes(mcp, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def allowed(request):
        host = request.headers.get("host")
        origin = request.headers.get("origin")
        return host in hosts and (origin is None or origin == f"http://{host}")

    @mcp.custom_route("/play", methods=["GET"])
    async def page(request: Request):
        if not allowed(request):
            return Response(status_code=403)
        return HTMLResponse(Path(__file__).with_name("play.html").read_text())

    @mcp.custom_route("/play/api", methods=["POST"])
    async def api(request: Request):
        if not allowed(request):
            return Response(status_code=403)
        if "application/json" not in request.headers.get("content-type", ""):
            return Response(status_code=415)
        try:
            payload = await request.json()
            if payload["tool"] not in {"start_trial", "observe", "jog_arm", "finish_trial"}:
                raise ValueError("Unknown play tool")
            blocks = await mcp.call_tool(payload["tool"], payload["arguments"])
            if isinstance(blocks, tuple):
                blocks = blocks[0]
            result = json.loads(blocks[0].text)
            images = [block for block in blocks if block.type == "image"]
            result["images"] = {
                name: f"data:image/png;base64,{block.data}"
                for name, block in zip(result["camera_order"], images, strict=True)
            }
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except Exception as error:  # noqa: BLE001 - report tool errors at HTTP boundary
            return JSONResponse({"error": str(error)}, status_code=400)
