import sys
import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse
from src.models import ChatCompletionRequest, ChatCompletionResponse, Choice, Message, ChatCompletionChunk, ChunkChoice, ChunkDelta, ModelList, Model
from src.relay import CommandBuilder, Executor
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
    """回傳動態模型清單 (FR-006)"""
    return ModelList(data=model_registry.get_models(api_key=api_key))

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    api_key: str = Depends(verify_auth)
):
    logger.info(f"Received chat completion request for model: {request.model}, stream={request.stream}")
    try:
        # Session Management Logic
        history_messages = request.messages[:-1]
        current_message = request.messages[-1]
        
        history_hash = session_manager.calculate_history_hash(history_messages)
        session = session_manager.get_session_by_hash(history_hash)
        
        session_id = None
        workspace_dir = None
        is_session_hit = False
        
        if session:
            session_id = session["session_id"]
            workspace_dir = session.get("workspace_dir")
            is_session_hit = True
            logger.debug(f"Session Hit: Resuming session {session_id} for hash {history_hash[:8]}...")
        else:
            title = current_message.content[:50]
            session_id = session_manager.create_session(history_hash, title)
            # Re-fetch session to get workspace_dir
            new_session = session_manager.get_session_by_hash(history_hash)
            if new_session:
                workspace_dir = new_session.get("workspace_dir")
            logger.debug(f"Session Miss: Created new session {session_id} for hash {history_hash[:8]}...")

        # 如果是新 session (或者 session 未命中)，發送完整歷史；如果是續傳，只發送最後一條訊息
        if is_session_hit:
            messages_to_send = [current_message]
            logger.debug("Sending latest message only to existing session.")
        else:
            messages_to_send = request.messages
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
                        yield f"data: {chunk_data.model_dump_json()}\n\n"
                    
                    # End of stream
                    logger.debug("Stream finished successfully")
                    yield "data: [DONE]\n\n"
                    
                    # Update Session Hash
                    response_text = "".join(full_content)
                    new_history = request.messages + [Message(role="assistant", content=response_text)]
                    new_hash = session_manager.calculate_history_hash(new_history)
                    session_manager.update_session_hash(history_hash, new_hash)
                    logger.debug(f"Updated session hash: {history_hash[:8]}... -> {new_hash[:8]}...")
                    
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    error_json = json.dumps({"error": {"message": str(e), "type": "stream_error"}})
                    yield f"data: {error_json}\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")
        else:
            content = await executor.run_non_stream(cmd, cwd=workspace_dir)
            
            # Update Session Hash
            new_history = request.messages + [Message(role="assistant", content=content)]
            new_hash = session_manager.calculate_history_hash(new_history)
            session_manager.update_session_hash(history_hash, new_hash)
            logger.debug(f"Updated session hash: {history_hash[:8]}... -> {new_hash[:8]}...")
            
            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4()}",
                created=int(time.time()),
                model=request.model,
                choices=[
                    Choice(
                        index=0,
                        message=Message(role="assistant", content=content),
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
    parser.add_argument("--update-model", action="store_true", help="Update model list from cursor-agent")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--clear", action="store_true", help="Clear sessions.json and .cursor-relay directory")
    
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
            relay_dir = config.CURSOR_RELAY_BASE
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
    
    uvicorn.run(
        "src.main:app",
        host=config.HOST,
        port=config.PORT,
        log_level=config.LOG_LEVEL.lower(),
        reload=args.reload
    )
