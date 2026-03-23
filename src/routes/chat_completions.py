"""Chat Completions API endpoint."""
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.config import config, logger
from src.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
    Choice,
    ChunkChoice,
    ChunkDelta,
    Message,
)
from src.relay import CommandBuilder, extract_workspace_from_messages
from src.routes.common import (
    resolve_session_and_build,
    update_session_after_response,
    verify_auth,
)

router = APIRouter()


def _build_think_block(builder: CommandBuilder, session_id: str) -> str:
    """Build think block with session info and available commands."""
    command_labels = builder.slash_loader.get_command_labels()
    commands_str = "\n" + "\n".join(command_labels) if command_labels else "(none)"
    return f"<think>\nSession ID: {session_id}\nAvailable Commands: {commands_str}\n</think>\n\n"


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    api_key: str = Depends(verify_auth),
):
    logger.info(f"Received chat completion request for model: {request.model}, stream={request.stream}")
    try:
        custom_workspace, custom_session_id, cleaned_messages = extract_workspace_from_messages(request.messages)

        ctx = resolve_session_and_build(
            cleaned_messages=cleaned_messages,
            model=request.model,
            api_key=api_key,
            stream=request.stream,
            custom_session_id=custom_session_id,
            custom_workspace=custom_workspace,
        )

        should_add_think = config.ENABLE_INFO_IN_THINK and not ctx.is_session_hit

        if request.stream:
            async def event_generator():
                req_id = f"chatcmpl-{uuid.uuid4()}"
                created = int(time.time())
                full_content = []

                logger.debug("Starting stream generation")
                try:
                    async for chunk in ctx.executor.run_stream(ctx.cmd, cwd=ctx.workspace_dir):
                        full_content.append(chunk)
                        chunk_data = ChatCompletionChunk(
                            id=req_id,
                            created=created,
                            model=request.model,
                            choices=[
                                ChunkChoice(
                                    index=0,
                                    delta=ChunkDelta(content=chunk)
                                )
                            ]
                        )
                        yield f"data: {chunk_data.model_dump_json(exclude_none=True)}\n\n"

                    if not full_content:
                        logger.warning("Stream produced no output from executor")
                        return

                    if should_add_think:
                        think_chunk = ChatCompletionChunk(
                            id=req_id,
                            created=created,
                            model=request.model,
                            choices=[
                                ChunkChoice(
                                    index=0,
                                    delta=ChunkDelta(content=_build_think_block(ctx.builder, ctx.session_id))
                                )
                            ]
                        )
                        yield f"data: {think_chunk.model_dump_json(exclude_none=True)}\n\n"

                    final_chunk = ChatCompletionChunk(
                        id=req_id,
                        created=created,
                        model=request.model,
                        choices=[
                            ChunkChoice(
                                index=0,
                                delta=ChunkDelta(),
                                finish_reason="stop"
                            )
                        ]
                    )
                    yield f"data: {final_chunk.model_dump_json(exclude_none=True)}\n\n"

                    logger.debug("Stream finished successfully")
                    yield "data: [DONE]\n\n"

                    update_session_after_response(
                        ctx.cleaned_messages, "".join(full_content), ctx.old_hash
                    )

                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    error_json = json.dumps({"error": {"message": str(e), "type": "stream_error"}})
                    yield f"data: {error_json}\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")
        else:
            content = await ctx.executor.run_non_stream(ctx.cmd, cwd=ctx.workspace_dir)
            think_block = _build_think_block(ctx.builder, ctx.session_id) if (should_add_think and content) else ""
            content_with_think = (think_block or "") + content

            update_session_after_response(ctx.cleaned_messages, content, ctx.old_hash)

            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4()}",
                created=int(time.time()),
                model=request.model,
                choices=[
                    Choice(
                        index=0,
                        message=Message(role="assistant", content=content_with_think),
                        finish_reason="stop"
                    )
                ]
            )

    except RuntimeError as e:
        logger.error(f"CLI Error: {e}")
        raise HTTPException(status_code=500, detail={"error": {"message": str(e), "type": "cli_error"}})
    except Exception as e:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail=str(e))
