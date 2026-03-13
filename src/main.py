import sys
import uvicorn
from dataclasses import dataclass
from typing import List, Optional, Tuple
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse
from src.models import (
    ChatCompletionRequest, ChatCompletionResponse, Choice, Message,
    ChatCompletionChunk, ChunkChoice, ChunkDelta, ModelList, Model,
    ResponseCreateRequest, ResponseObject, ResponseOutputMessage, ResponseOutputText,
)
from src.relay import CommandBuilder, Executor, extract_workspace_from_messages
from src.slash_command_loader import SlashCommandLoader
from src.config import config, logger
from src.model_registry import model_registry, ModelRegistry
from src.session_manager import SessionManager
import shutil
import time
import uuid
import json

app = FastAPI(title="Cursor CLI Proxy")

# Ensure config validation
config.validate()

# Initialize ModelRegistry (load from cache file or use defaults)
model_registry.initialize()

# Initialize SessionManager
session_manager = SessionManager()

async def verify_auth(authorization: str = Header(None)) -> str:
    """Resolve API key: use CURSOR_KEY if set, otherwise require valid Bearer token."""
    cursor_key = (config.CURSOR_KEY or "").strip().strip("'\"")
    if cursor_key:
        return cursor_key
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication header")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing API key in Bearer token")
    return token

def _build_think_block(builder: CommandBuilder, session_id: str) -> str:
    """Build think block with session info and available commands."""
    command_labels = builder.slash_loader.get_command_labels()
    commands_str = "\n" + "\n".join(command_labels) if command_labels else "(none)"
    return f"<think>\nSession ID: {session_id}\nAvailable Commands: {commands_str}\n</think>\n\n"


def _check_session_storage() -> bool:
    try:
        session_manager.load_sessions()
        return True
    except Exception:
        return False


@app.get("/health")
async def health():
    checks = {
        "cursor_agent": shutil.which("cursor-agent") is not None,
        "model_registry": model_registry._models is not None,
        "session_storage": _check_session_storage(),
    }
    status = "healthy" if all(checks.values()) else "degraded"
    return {"status": status, "checks": checks}


@app.get("/v1/models", response_model=ModelList)
async def list_models(api_key: str = Depends(verify_auth)):
    """Return dynamic model list"""
    return ModelList(data=model_registry.get_models(api_key=api_key))


# ── Shared helpers ────────────────────────────────────────────────────

@dataclass
class SessionContext:
    session_id: str
    workspace_dir: Optional[str]
    is_session_hit: bool
    builder: CommandBuilder
    executor: Executor
    cmd: List[str]
    cleaned_messages: List[Message]
    old_hash: str


def _resolve_session_and_build(
    cleaned_messages: List[Message],
    model: str,
    api_key: str,
    stream: bool,
    custom_session_id: Optional[str] = None,
    custom_workspace: Optional[str] = None,
) -> SessionContext:
    """Shared session resolution, message preparation, and command building."""
    history_messages = cleaned_messages[:-1]
    current_message = cleaned_messages[-1]

    history_hash = session_manager.calculate_history_hash(history_messages)
    session = session_manager.get_session_by_hash(history_hash)

    session_id = None
    workspace_dir = None
    is_session_hit = False
    custom_session_hash = None

    if custom_session_id:
        existing_session = session_manager.get_session_by_id(custom_session_id)
        if existing_session:
            session_id = custom_session_id
            workspace_dir = existing_session.get("workspace_dir") or custom_workspace
            is_session_hit = True
            custom_session_hash = session_manager.get_hash_by_session_id(custom_session_id)
            logger.info(f"Using custom session_id: {session_id}")
        else:
            logger.warning(f"Custom session_id '{custom_session_id}' not found, falling back to normal flow")

    if session_id is None and session:
        session_id = session["session_id"]
        workspace_dir = session.get("workspace_dir")
        is_session_hit = True
        logger.debug(f"Session Hit: Resuming session {session_id} for hash {history_hash[:8]}...")
    elif session_id is None:
        title = current_message.get_text_content()[:50]
        session_id = session_manager.create_session(history_hash, title, custom_workspace=custom_workspace)
        new_session = session_manager.get_session_by_hash(history_hash)
        if new_session:
            workspace_dir = new_session.get("workspace_dir")
        logger.debug(f"Session Miss: Created new session {session_id} for hash {history_hash[:8]}...")

    if is_session_hit:
        messages_to_send = [current_message]
        logger.debug("Sending latest message only to existing session.")
    else:
        messages_to_send = list(cleaned_messages)
        logger.debug(f"Sending full history ({len(messages_to_send)} messages) to new session.")

    if config.ENABLE_SKILLS_IN_PROMPT and not is_session_hit:
        skills_loader = SlashCommandLoader(workspace_dir)
        skills_xml = skills_loader.get_skills_metadata_xml()
        if skills_xml:
            skills_message = Message(role="system", content=skills_xml)
            messages_to_send = [skills_message] + messages_to_send
            logger.info(f"Injected skills metadata ({len(skills_loader.entries)} entries) into system prompt")

    builder = CommandBuilder(
        model=model,
        api_key=api_key,
        messages=messages_to_send,
        session_id=session_id,
        workspace_dir=workspace_dir,
    )
    cmd = builder.build(stream=stream)
    executor = Executor()

    return SessionContext(
        session_id=session_id,
        workspace_dir=workspace_dir,
        is_session_hit=is_session_hit,
        builder=builder,
        executor=executor,
        cmd=cmd,
        cleaned_messages=cleaned_messages,
        old_hash=custom_session_hash or history_hash,
    )


def _update_session_after_response(
    cleaned_messages: List[Message],
    response_text: str,
    old_hash: str,
) -> None:
    new_history = cleaned_messages + [Message(role="assistant", content=response_text)]
    new_hash = session_manager.calculate_history_hash(new_history)
    session_manager.update_session_hash(old_hash, new_hash)
    logger.debug(f"Updated session hash: {old_hash[:8]}... -> {new_hash[:8]}...")


# ── Chat Completions endpoint ─────────────────────────────────────────

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    api_key: str = Depends(verify_auth)
):
    request.model = ModelRegistry.to_cli_id(request.model)
    logger.info(f"Received chat completion request for model: {request.model}, stream={request.stream}")
    try:
        custom_workspace, custom_session_id, cleaned_messages = extract_workspace_from_messages(request.messages)

        ctx = _resolve_session_and_build(
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

                    _update_session_after_response(
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

            _update_session_after_response(ctx.cleaned_messages, content, ctx.old_hash)

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


# ── Responses API endpoint ────────────────────────────────────────────

@app.post("/v1/responses")
async def create_response(
    request: ResponseCreateRequest,
    api_key: str = Depends(verify_auth),
):
    model = ModelRegistry.to_cli_id(request.model)
    logger.info(f"Received responses request for model: {model}, stream={request.stream}")

    try:
        messages = request.to_messages()
        if not messages:
            raise HTTPException(status_code=400, detail="input must produce at least one message")

        custom_session_id = request.previous_response_id
        ctx = _resolve_session_and_build(
            cleaned_messages=messages,
            model=model,
            api_key=api_key,
            stream=request.stream,
            custom_session_id=custom_session_id,
        )

        resp_id = f"resp_{ctx.session_id}"
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"

        if request.stream:
            async def response_event_generator():
                created_at = int(time.time())
                full_content: List[str] = []

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

                # response.output_item.added
                out_msg = {
                    "type": "message",
                    "id": msg_id,
                    "status": "in_progress",
                    "role": "assistant",
                    "content": [],
                }
                yield f"event: response.output_item.added\ndata: {json.dumps({'type': 'response.output_item.added', 'output_index': 0, 'item': out_msg})}\n\n"

                # response.content_part.added
                content_part = {"type": "output_text", "text": "", "annotations": []}
                yield f"event: response.content_part.added\ndata: {json.dumps({'type': 'response.content_part.added', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': content_part})}\n\n"

                try:
                    async for chunk in ctx.executor.run_stream(ctx.cmd, cwd=ctx.workspace_dir):
                        full_content.append(chunk)
                        delta_event = {
                            "type": "response.output_text.delta",
                            "item_id": msg_id,
                            "output_index": 0,
                            "content_index": 0,
                            "delta": chunk,
                        }
                        yield f"event: response.output_text.delta\ndata: {json.dumps(delta_event)}\n\n"

                    full_text = "".join(full_content)

                    # response.output_text.done
                    text_done = {
                        "type": "response.output_text.done",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "text": full_text,
                    }
                    yield f"event: response.output_text.done\ndata: {json.dumps(text_done)}\n\n"

                    # response.completed
                    completed_resp = ResponseObject(
                        id=resp_id,
                        created_at=created_at,
                        status="completed",
                        model=model,
                        output=[
                            ResponseOutputMessage(
                                id=msg_id,
                                status="completed",
                                content=[ResponseOutputText(text=full_text)],
                            )
                        ],
                        previous_response_id=request.previous_response_id,
                        temperature=request.temperature,
                        max_output_tokens=request.max_output_tokens,
                    )
                    yield f"event: response.completed\ndata: {json.dumps({'type': 'response.completed', 'response': completed_resp.model_dump()})}\n\n"

                    _update_session_after_response(ctx.cleaned_messages, full_text, ctx.old_hash)

                except Exception as e:
                    logger.error(f"Responses stream error: {e}")
                    error_event = {"type": "error", "message": str(e)}
                    yield f"event: error\ndata: {json.dumps(error_event)}\n\n"

            return StreamingResponse(response_event_generator(), media_type="text/event-stream")
        else:
            content = await ctx.executor.run_non_stream(ctx.cmd, cwd=ctx.workspace_dir)

            _update_session_after_response(ctx.cleaned_messages, content, ctx.old_hash)

            return ResponseObject(
                id=resp_id,
                model=model,
                output=[
                    ResponseOutputMessage(
                        id=msg_id,
                        status="completed",
                        content=[ResponseOutputText(text=content)],
                    )
                ],
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


if __name__ == "__main__":
    import argparse
    import os
    import shutil
    
    parser = argparse.ArgumentParser(description="Cursor CLI Proxy")
    parser.add_argument("--update-model", action="store_true", help="Update model list from cursor-agent and exit")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--clear", action="store_true", help="Clear sessions.json and temporary directory and exit")
    
    # Use parse_known_args to avoid errors if other args are passed (though we expect mostly these)
    args, _ = parser.parse_known_args()
    
    # Handle update-model command
    if args.update_model:
        try:
            logger.info("Updating model list from cursor-agent...")
            model_registry.initialize(update=True)
            logger.info("✓ Model list updated successfully!")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Error updating model list: {e}")
            sys.exit(1)
    
    # Handle clear command
    if args.clear:
        try:
            # Clear sessions.json
            sessions_file = "sessions.json"
            if os.path.exists(sessions_file):
                logger.info(f"Clearing {sessions_file}...")
                with open(sessions_file, "w", encoding="utf-8") as f:
                    json.dump({"sessions": {}}, f, ensure_ascii=False, indent=2)
                logger.info(f"✓ {sessions_file} cleared successfully")
            else:
                logger.info(f"{sessions_file} does not exist, skipping")
            
            # Clear sessions.json.lock
            lock_file = "sessions.json.lock"
            if os.path.exists(lock_file):
                logger.info(f"Removing {lock_file}...")
                os.remove(lock_file)
                logger.info(f"✓ {lock_file} removed successfully")
            
            # Clear cursor-relay base directory
            from src.config import CURSOR_CLI_PROXY_TMP
            relay_dir = CURSOR_CLI_PROXY_TMP
            if os.path.exists(relay_dir):
                logger.info(f"Removing {relay_dir} directory...")
                shutil.rmtree(relay_dir)
                logger.info(f"✓ {relay_dir} directory removed successfully")
            else:
                logger.info(f"{relay_dir} directory does not exist, skipping")
            
            logger.info("All session data cleared successfully!")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Error clearing session data: {e}")
            sys.exit(1)
    
    # Build uvicorn config
    uvicorn_kwargs = {
        "host": config.HOST,
        "port": config.PORT,
        "log_level": config.LOG_LEVEL.lower(),
        "reload": args.reload,
    }
    
    # Add SSL configuration if HTTPS is enabled
    if config.ENABLE_HTTPS:
        import os
        # Check that paths are configured (non-empty)
        if not config.HTTPS_CERT_PATH:
            logger.error("HTTPS is enabled but HTTPS_CERT_PATH is not configured")
            sys.exit(1)
        if not config.HTTPS_KEY_PATH:
            logger.error("HTTPS is enabled but HTTPS_KEY_PATH is not configured")
            sys.exit(1)
        # Check that files exist at the configured paths
        if not os.path.exists(config.HTTPS_CERT_PATH):
            logger.error(f"HTTPS certificate not found: {config.HTTPS_CERT_PATH}")
            sys.exit(1)
        if not os.path.exists(config.HTTPS_KEY_PATH):
            logger.error(f"HTTPS key not found: {config.HTTPS_KEY_PATH}")
            sys.exit(1)
        uvicorn_kwargs["ssl_certfile"] = config.HTTPS_CERT_PATH
        uvicorn_kwargs["ssl_keyfile"] = config.HTTPS_KEY_PATH
        logger.info(f"HTTPS enabled with cert: {config.HTTPS_CERT_PATH}")
    
    uvicorn.run("src.main:app", **uvicorn_kwargs)
