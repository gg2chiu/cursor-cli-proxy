"""
Temporary file handling utilities for saving content and images.
"""
import os
import hashlib
import base64
from typing import Optional, Tuple

from loguru import logger
from src.config import CURSOR_CLI_PROXY_TMP


# Threshold for when to save content to file (in characters)
# Command line limit is typically 128KB-2MB, but let's be conservative
CONTENT_SIZE_THRESHOLD = 4000


def save_content_to_temp_file(content: str, filename_hint: str = None, extension: str = None) -> str:
    """
    Save text content to a temporary file and return the file path.
    Uses a hash-based filename to avoid duplicates.
    """
    # Create temp directory if not exists
    os.makedirs(CURSOR_CLI_PROXY_TMP, exist_ok=True)
    
    # Generate unique filename based on content hash
    content_hash = hashlib.md5(content.encode()).hexdigest()[:12]
    
    # Determine file extension
    ext = extension or ".txt"
    if not extension and filename_hint:
        # Extract extension from filename hint
        if "." in filename_hint:
            ext = "." + filename_hint.rsplit(".", 1)[-1].lower()
            # Limit extension to reasonable ones
            if len(ext) > 10 or not ext[1:].isalnum():
                ext = ".txt"
    
    filename = f"upload_{content_hash}{ext}"
    filepath = os.path.join(CURSOR_CLI_PROXY_TMP, filename)
    
    # Write content to file
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    
    logger.debug(f"Saved text content to temp file: {filepath} ({len(content)} bytes)")
    return filepath


def save_image_to_temp_file(data_url: str) -> Optional[str]:
    """
    Save base64 image to a temporary file and return the file path.
    Supports data URLs like: data:image/jpeg;base64,/9j/4AAQ...
    """
    # Parse data URL
    if not data_url.startswith("data:"):
        logger.warning(f"Invalid data URL format: {data_url[:50]}...")
        return None
    
    try:
        # Format: data:image/jpeg;base64,<data>
        header, encoded = data_url.split(",", 1)
        
        # Extract MIME type
        mime_part = header.split(";")[0]  # data:image/jpeg
        mime_type = mime_part.split(":")[1] if ":" in mime_part else "image/png"
        
        # Determine extension from MIME type
        ext_map = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }
        ext = ext_map.get(mime_type, ".png")
        
        # Decode base64
        image_data = base64.b64decode(encoded)
        
        # Generate filename
        content_hash = hashlib.md5(image_data).hexdigest()[:12]
        filename = f"image_{content_hash}{ext}"
        filepath = os.path.join(CURSOR_CLI_PROXY_TMP, filename)
        
        # Create temp directory if not exists
        os.makedirs(CURSOR_CLI_PROXY_TMP, exist_ok=True)
        
        # Write image to file
        with open(filepath, "wb") as f:
            f.write(image_data)
        
        logger.debug(f"Saved image to temp file: {filepath} ({len(image_data)} bytes)")
        return filepath
        
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return None


def extract_filename_and_content(text: str) -> Tuple[Optional[str], str]:
    """
    Try to extract filename from first line and return (filename, content).
    Pattern: "filename.ext\n<actual content>"
    Returns (None, original_text) if no filename pattern detected.
    """
    lines = text.split("\n", 1)
    if len(lines) < 2:
        return None, text
    
    first_line = lines[0].strip()
    rest_content = lines[1]
    
    # Check if first line looks like a filename (has extension, reasonable length, no spaces at start)
    if len(first_line) < 300 and "." in first_line and not first_line.startswith(" "):
        # Check if it has a valid-looking extension
        ext = first_line.rsplit(".", 1)[-1].lower()
        if len(ext) <= 10 and ext.isalnum():
            logger.debug(f"Detected filename: {first_line}")
            return first_line, rest_content
    
    return None, text
