import sys
import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse
from src.models import ChatCompletionRequest, ChatCompletionResponse, Choice, Message, ChatCompletionChunk, ChunkChoice, ChunkDelta, ModelList, Model
from src.relay import CommandBuilder, Executor, extract_workspace_from_messages
from src.config import config, logger
from src.model_registry import model_registry
from src.session_manager import SessionManager
import time
import uuid
import json

app = FastAPI(title="Cursor CLI Proxy")

# Ensure config validation
config.validate()

# Initialize SessionManager
session_manager = SessionManager()

async def verify_auth(authorization: str = Header(None)):
    if not authorization:
        if config.CURSOR_KEY:
            return config.CURSOR_KEY
        raise HTTPException(status_code=401, detail="Missing authentication header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication header")
    return authorization.split(" ")[1]

@app.get("/v1/models", response_model=ModelList)
async def list_models(api_key: str = Depends(verify_auth)):
    """Return dynamic model list"""
    return ModelList(data=model_registry.get_models(api_key=api_key))

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    api_key: str = Depends(verify_auth)
):
    logger.info(f"Received chat completion request for model: {request.model}, stream={request.stream}")
    try:
        # Extract workspace and session_id from messages (if present in system prompt)
        custom_workspace, custom_session_id, cleaned_messages = extract_workspace_from_messages(request.messages)
        
        # Session Management Logic
        history_messages = cleaned_messages[:-1]
        current_message = cleaned_messages[-1]
        
        history_hash = session_manager.calculate_history_hash(history_messages)
        session = session_manager.get_session_by_hash(history_hash)
        
        session_id = None
        workspace_dir = None
        is_session_hit = False
        custom_session_hash = None
        
        # If custom session_id is provided, use it directly (if it exists)
        if custom_session_id:
            existing_session = session_manager.get_session_by_id(custom_session_id)
            if existing_session:
                session_id = custom_session_id
                workspace_dir = existing_session.get("workspace_dir") or custom_workspace
                is_session_hit = True
                custom_session_hash = session_manager.get_hash_by_session_id(custom_session_id)
                logger.info(f"Using custom session_id from system prompt: {session_id}")
            else:
                logger.warning(f"Custom session_id '{custom_session_id}' not found, falling back to normal flow")
                custom_session_id = None

        if session_id is None and session:
            session_id = session["session_id"]
            workspace_dir = session.get("workspace_dir")
            is_session_hit = True
            logger.debug(f"Session Hit: Resuming session {session_id} for hash {history_hash[:8]}...")
        elif session_id is None:
            title = current_message.get_text_content()[:50]
            # Pass custom_workspace when creating new session
            session_id = session_manager.create_session(history_hash, title, custom_workspace=custom_workspace)
            # Re-fetch session to get workspace_dir
            new_session = session_manager.get_session_by_hash(history_hash)
            if new_session:
                workspace_dir = new_session.get("workspace_dir")
            logger.debug(f"Session Miss: Created new session {session_id} for hash {history_hash[:8]}...")

        # If it's a new session (or session miss), send full history; if resuming, only send the last message
        if is_session_hit:
            messages_to_send = [current_message]
            logger.debug("Sending latest message only to existing session.")
        else:
            messages_to_send = cleaned_messages
            logger.debug(f"Sending full history ({len(messages_to_send)} messages) to new session.")

        # Build command with session_id and the appropriate messages
        builder = CommandBuilder(
            model=request.model,
            api_key=api_key,
            messages=messages_to_send,
            session_id=session_id,
            workspace_dir=workspace_dir
        )
        cmd = builder.build(stream=request.stream)
        
        executor = Executor()
        
        # Build think block with session_id and loaded slash commands (only for new sessions, if enabled)
        think_block = ""
        if config.ENABLE_INFO_IN_THINK and not is_session_hit:
            command_labels = builder.slash_loader.get_command_labels()
            commands_str = "\n" + "\n".join(command_labels) if command_labels else "(none)"
            think_block = f"<think>\nSession ID: {session_id}\nAvailable Commands: {commands_str}\n</think>\n\n"
        
        if request.stream:
            async def event_generator():
                req_id = f"chatcmpl-{uuid.uuid4()}"
                created = int(time.time())
                full_content = []
                
                logger.debug("Starting stream generation")
                try:                    
                    async for chunk in executor.run_stream(cmd, cwd=workspace_dir):
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

                    # Send think block as the last chunk (only for new sessions)
                    if think_block:
                        think_chunk = ChatCompletionChunk(
                            id=req_id,
                            created=created,
                            model=request.model,
                            choices=[
                                ChunkChoice(
                                    index=0,
                                    delta=ChunkDelta(content=think_block)
                                )
                            ]
                        )
                        yield f"data: {think_chunk.model_dump_json(exclude_none=True)}\n\n"

                    # Send final chunk with finish_reason="stop" before [DONE]
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
                    
                    # End of stream
                    logger.debug("Stream finished successfully")
                    yield "data: [DONE]\n\n"
                    
                    # Update Session Hash (skip if custom session_id is used)
                    response_text = "".join(full_content)
                    new_history = cleaned_messages + [Message(role="assistant", content=response_text)]
                    new_hash = session_manager.calculate_history_hash(new_history)
                    old_hash = custom_session_hash or history_hash
                    session_manager.update_session_hash(old_hash, new_hash)
                    logger.debug(f"Updated session hash: {old_hash[:8]}... -> {new_hash[:8]}...")
                    
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    error_json = json.dumps({"error": {"message": str(e), "type": "stream_error"}})
                    yield f"data: {error_json}\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")
        else:
            content = await executor.run_non_stream(cmd, cwd=workspace_dir)
            
            # Prepend think block to content (only for new sessions)
            content_with_think = think_block + content if think_block else content
            
            # Update Session Hash (use original hash for custom session_id)
            new_history = cleaned_messages + [Message(role="assistant", content=content)]
            new_hash = session_manager.calculate_history_hash(new_history)
            old_hash = custom_session_hash or history_hash
            session_manager.update_session_hash(old_hash, new_hash)
            logger.debug(f"Updated session hash: {old_hash[:8]}... -> {new_hash[:8]}...")
            
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
