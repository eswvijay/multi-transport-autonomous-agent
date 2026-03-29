from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder

from transports.agui.agent_adapter import AgUiAgentAdapter


def create_agui_app(agent_adapter: AgUiAgentAdapter, path: str = "/", ping_path: str | None = "/ping") -> FastAPI:
    app = FastAPI(title=f"Agent — {agent_adapter.name}")

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.post(path)
    async def agent_endpoint(input_data: RunAgentInput, request: Request):
        encoder = EventEncoder(accept=request.headers.get("accept"))

        async def event_generator():
            async for event in agent_adapter.run(input_data):
                try:
                    yield encoder.encode(event)
                except Exception as e:
                    from ag_ui.core import RunErrorEvent, EventType
                    yield encoder.encode(RunErrorEvent(type=EventType.RUN_ERROR, message=str(e), code="ENCODING_ERROR"))
                    break

        return StreamingResponse(event_generator(), media_type=encoder.get_content_type())

    if ping_path:
        @app.get(ping_path)
        async def ping():
            return {"status": "healthy"}

    return app
