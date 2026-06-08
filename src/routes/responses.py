"""Responses API endpoint."""
import json
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.config import config, logger
from src.models import (
    ResponseCreateRequest,
    ResponseObject,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
    ResponseSummaryText,
)
from src.relay import CommandBuilder, extract_workspace_from_messages
from src.routes.common import (
    resolve_session_and_build,
    update_session_after_response,
    verify_auth,
)

router = APIRouter()


def _build_think_summary_text(builder: CommandBuilder, session_id: str) -> str:
    """Build plain-text summary for a Responses API reasoning item."""
    command_labels = builder.slash_loader.get_command_labels()
    commands_str = "\n" + "\n".join(command_labels) if command_labels else "(none)"
    return f"Session ID: {session_id}\nAvailable Commands: {commands_str}"


@router.post("/v1/responses")
async def create_response(
    request: ResponseCreateRequest,
    api_key: Optional[str] = Depends(verify_auth),
):
    model = request.model
    logger.info(f"Received responses request for model: {model}, stream={request.stream}")

    try:
        messages = request.to_messages()
        if not messages:
            raise HTTPException(status_code=400, detail="input must produce at least one message")

        custom_workspace, tag_session_id, cleaned_messages = extract_workspace_from_messages(messages)

        prev_id = request.previous_response_id
        prev_session_id = prev_id.removeprefix("resp_") if prev_id else None
        custom_session_id = prev_session_id or tag_session_id

        ctx = resolve_session_and_build(
            cleaned_messages=cleaned_messages,
            model=model,
            api_key=api_key,
            stream=request.stream,
            custom_session_id=custom_session_id,
            custom_workspace=custom_workspace,
        )

        resp_id = f"resp_{ctx.session_id}"
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        should_add_think = config.ENABLE_INFO_IN_THINK and not ctx.is_session_hit

        reasoning_item: Optional[ResponseReasoningItem] = None
        if should_add_think:
            reasoning_item = ResponseReasoningItem(
                id=f"rs_{uuid.uuid4().hex[:24]}",
                summary=[ResponseSummaryText(
                    text=_build_think_summary_text(ctx.builder, ctx.session_id),
                )],
            )

        if request.stream:
            async def response_event_generator():
                created_at = int(time.time())
                full_content: List[str] = []
                msg_output_index = 0

                # response.created
                created_resp = ResponseObject(
                    id=resp_id,
                    created_at=created_at,
                    status="in_progress",
                    model=model,
                    output=[],
                    previous_response_id=request.previous_response_id,
                    temperature=request.temperature,
                    max_output_tokens=request.max_output_tokens,
                )
                yield f"event: response.created\ndata: {json.dumps({'type': 'response.created', 'response': created_resp.model_dump()})}\n\n"

                if reasoning_item:
                    rs_id = reasoning_item.id
                    rs_dump = reasoning_item.model_dump()
                    summary_text = reasoning_item.summary[0].text
                    summary_part = {"type": "summary_text", "text": ""}

                    yield f"event: response.output_item.added\ndata: {json.dumps({'type': 'response.output_item.added', 'output_index': 0, 'item': rs_dump})}\n\n"

                    yield f"event: response.reasoning_summary_part.added\ndata: {json.dumps({'type': 'response.reasoning_summary_part.added', 'item_id': rs_id, 'output_index': 0, 'summary_index': 0, 'part': summary_part})}\n\n"

                    yield f"event: response.reasoning_summary_text.delta\ndata: {json.dumps({'type': 'response.reasoning_summary_text.delta', 'item_id': rs_id, 'output_index': 0, 'summary_index': 0, 'delta': summary_text})}\n\n"

                    yield f"event: response.reasoning_summary_text.done\ndata: {json.dumps({'type': 'response.reasoning_summary_text.done', 'item_id': rs_id, 'output_index': 0, 'summary_index': 0, 'text': summary_text})}\n\n"

                    yield f"event: response.reasoning_summary_part.done\ndata: {json.dumps({'type': 'response.reasoning_summary_part.done', 'item_id': rs_id, 'output_index': 0, 'summary_index': 0, 'part': {'type': 'summary_text', 'text': summary_text}})}\n\n"

                    yield f"event: response.output_item.done\ndata: {json.dumps({'type': 'response.output_item.done', 'output_index': 0, 'item': rs_dump})}\n\n"

                    msg_output_index = 1

                # response.output_item.added (message)
                out_msg = {
                    "type": "message",
                    "id": msg_id,
                    "status": "in_progress",
                    "role": "assistant",
                    "content": [],
                }
                yield f"event: response.output_item.added\ndata: {json.dumps({'type': 'response.output_item.added', 'output_index': msg_output_index, 'item': out_msg})}\n\n"

                # response.content_part.added
                content_part = {"type": "output_text", "text": "", "annotations": []}
                yield f"event: response.content_part.added\ndata: {json.dumps({'type': 'response.content_part.added', 'item_id': msg_id, 'output_index': msg_output_index, 'content_index': 0, 'part': content_part})}\n\n"

                try:
                    async for chunk in ctx.executor.run_stream(ctx.cmd, cwd=ctx.workspace_dir):
                        full_content.append(chunk)
                        delta_event = {
                            "type": "response.output_text.delta",
                            "item_id": msg_id,
                            "output_index": msg_output_index,
                            "content_index": 0,
                            "delta": chunk,
                        }
                        yield f"event: response.output_text.delta\ndata: {json.dumps(delta_event)}\n\n"

                    full_text = "".join(full_content)

                    # response.output_text.done
                    text_done = {
                        "type": "response.output_text.done",
                        "item_id": msg_id,
                        "output_index": msg_output_index,
                        "content_index": 0,
                        "text": full_text,
                    }
                    yield f"event: response.output_text.done\ndata: {json.dumps(text_done)}\n\n"

                    # response.content_part.done
                    yield f"event: response.content_part.done\ndata: {json.dumps({'type': 'response.content_part.done', 'item_id': msg_id, 'output_index': msg_output_index, 'content_index': 0, 'part': {'type': 'output_text', 'text': full_text, 'annotations': []}})}\n\n"

                    # response.output_item.done (message)
                    done_msg = {
                        "type": "message",
                        "id": msg_id,
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": full_text, "annotations": []}],
                    }
                    yield f"event: response.output_item.done\ndata: {json.dumps({'type': 'response.output_item.done', 'output_index': msg_output_index, 'item': done_msg})}\n\n"

                    # response.completed
                    completed_output: List = []
                    if reasoning_item:
                        completed_output.append(reasoning_item)
                    completed_output.append(
                        ResponseOutputMessage(
                            id=msg_id,
                            status="completed",
                            content=[ResponseOutputText(text=full_text)],
                        )
                    )
                    completed_resp = ResponseObject(
                        id=resp_id,
                        created_at=created_at,
                        status="completed",
                        model=model,
                        output=completed_output,
                        previous_response_id=request.previous_response_id,
                        temperature=request.temperature,
                        max_output_tokens=request.max_output_tokens,
                    )
                    yield f"event: response.completed\ndata: {json.dumps({'type': 'response.completed', 'response': completed_resp.model_dump()})}\n\n"

                    update_session_after_response(ctx.cleaned_messages, full_text, ctx.old_hash)

                except Exception as e:
                    logger.error(f"Responses stream error: {e}")
                    error_event = {"type": "error", "message": str(e)}
                    yield f"event: error\ndata: {json.dumps(error_event)}\n\n"

            return StreamingResponse(response_event_generator(), media_type="text/event-stream")
        else:
            content = await ctx.executor.run_non_stream(ctx.cmd, cwd=ctx.workspace_dir)

            update_session_after_response(ctx.cleaned_messages, content, ctx.old_hash)

            output_items: List = []
            if reasoning_item:
                output_items.append(reasoning_item)
            output_items.append(
                ResponseOutputMessage(
                    id=msg_id,
                    status="completed",
                    content=[ResponseOutputText(text=content)],
                )
            )

            return ResponseObject(
                id=resp_id,
                model=model,
                output=output_items,
                previous_response_id=request.previous_response_id,
                temperature=request.temperature,
                max_output_tokens=request.max_output_tokens,
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"CLI Error: {e}")
        raise HTTPException(status_code=500, detail={"error": {"message": str(e), "type": "cli_error"}})
    except Exception as e:
        logger.exception("Unexpected error in responses endpoint")
        raise HTTPException(status_code=500, detail=str(e))
