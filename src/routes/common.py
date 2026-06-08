"""Shared helpers for route handlers."""
import secrets
from dataclasses import dataclass
from typing import List, Optional

from fastapi import Header, HTTPException

from src.config import config, logger
from src.models import Message
from src.relay import CommandBuilder, Executor
from src.session_manager import SessionManager
from src.slash_command_loader import SlashCommandLoader

session_manager = SessionManager()


async def verify_auth(authorization: str = Header(None)) -> Optional[str]:
    """Authenticate the client against PROXY_PASSWORD (mandatory).

    The client sends PROXY_PASSWORD as the Bearer token / apiKey. On success,
    return the API key to use for cursor-agent: CURSOR_KEY if configured,
    otherwise None so cursor-agent falls back to its own login state.
    """
    proxy_password = (config.PROXY_PASSWORD or "").strip().strip("'\"")
    if not proxy_password:
        logger.error("PROXY_PASSWORD is not configured; rejecting request")
        raise HTTPException(status_code=500, detail="Server misconfiguration: PROXY_PASSWORD not set")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication header")
    token = authorization.split(" ", 1)[1].strip()
    if not token or not secrets.compare_digest(token.encode("utf-8"), proxy_password.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid API key")

    cursor_key = (config.CURSOR_KEY or "").strip().strip("'\"")
    return cursor_key or None


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


def resolve_session_and_build(
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


def update_session_after_response(
    cleaned_messages: List[Message],
    response_text: str,
    old_hash: str,
) -> None:
    new_history = cleaned_messages + [Message(role="assistant", content=response_text)]
    new_hash = session_manager.calculate_history_hash(new_history)
    session_manager.update_session_hash(old_hash, new_hash)
    logger.debug(f"Updated session hash: {old_hash[:8]}... -> {new_hash[:8]}...")
