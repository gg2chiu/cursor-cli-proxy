"""Tests for file/image upload functionality."""
import pytest
import os
import base64
import tempfile
from unittest.mock import patch

from src.models import (
    Message, 
    TextContentPart, 
    ImageContentPart, 
    ImageUrlDetail,
    ChatCompletionRequest
)
from src.relay import (
    save_content_to_temp_file,
    save_image_to_temp_file,
    extract_filename_and_content,
    CommandBuilder,
    CONTENT_SIZE_THRESHOLD
)


# ============================================================================
# Message Model Tests
# ============================================================================

class TestMessageMultimodalContent:
    """Test Message model with multimodal content."""
    
    def test_message_with_string_content(self):
        """Test that string content still works."""
        msg = Message(role="user", content="Hello world")
        assert msg.content == "Hello world"
        assert msg.get_text_content() == "Hello world"
    
    def test_message_with_text_content_parts(self):
        """Test message with list of text content parts."""
        msg = Message(
            role="user",
            content=[
                {"type": "text", "text": "First part"},
                {"type": "text", "text": "Second part"}
            ]
        )
        assert isinstance(msg.content, list)
        assert msg.get_text_content() == "First part\nSecond part"
    
    def test_message_with_image_content_part(self):
        """Test message with image content part."""
        msg = Message(
            role="user",
            content=[
                {"type": "text", "text": "What is this?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}}
            ]
        )
        text = msg.get_text_content()
        assert "What is this?" in text
        assert "[Image]" in text
    
    def test_message_with_typed_content_parts(self):
        """Test message with Pydantic model content parts."""
        msg = Message(
            role="user",
            content=[
                TextContentPart(type="text", text="Hello"),
                ImageContentPart(
                    type="image_url",
                    image_url=ImageUrlDetail(url="data:image/jpeg;base64,xyz")
                )
            ]
        )
        text = msg.get_text_content()
        assert "Hello" in text
        assert "[Image]" in text
    
    def test_chat_completion_request_with_multimodal(self):
        """Test ChatCompletionRequest accepts multimodal messages."""
        request = ChatCompletionRequest(
            model="gpt-4-vision",
            messages=[
                {"role": "system", "content": "You are helpful."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
                    ]
                }
            ]
        )
        assert len(request.messages) == 2
        assert isinstance(request.messages[1].content, list)


# ============================================================================
# File Content Processing Tests
# ============================================================================

class TestExtractFilenameAndContent:
    """Test extract_filename_and_content function."""
    
    def test_extract_json_filename(self):
        """Test extracting JSON filename from content."""
        text = "config.json\n{\"key\": \"value\"}"
        filename, content = extract_filename_and_content(text)
        assert filename == "config.json"
        assert content == "{\"key\": \"value\"}"
    
    def test_extract_txt_filename(self):
        """Test extracting TXT filename from content."""
        text = "readme.txt\nThis is the content\nwith multiple lines"
        filename, content = extract_filename_and_content(text)
        assert filename == "readme.txt"
        assert "This is the content" in content
    
    def test_extract_complex_filename(self):
        """Test extracting filename with special characters."""
        text = "【茉莉】《茉莉文集》0.0521ver (1).json\n{\"data\": true}"
        filename, content = extract_filename_and_content(text)
        assert filename == "【茉莉】《茉莉文集》0.0521ver (1).json"
        assert content == "{\"data\": true}"
    
    def test_no_filename_pattern(self):
        """Test content without filename pattern."""
        text = "This is just normal text without a filename"
        filename, content = extract_filename_and_content(text)
        assert filename is None
        assert content == text
    
    def test_single_line_content(self):
        """Test single line content (no newline)."""
        text = "Just one line"
        filename, content = extract_filename_and_content(text)
        assert filename is None
        assert content == text
    
    def test_very_long_first_line(self):
        """Test that very long first lines are not treated as filenames."""
        text = "A" * 400 + ".txt\nActual content"
        filename, content = extract_filename_and_content(text)
        assert filename is None  # Too long to be a filename


class TestSaveContentToTempFile:
    """Test save_content_to_temp_file function."""
    
    def test_save_text_content(self, tmp_path):
        """Test saving text content to temp file."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            content = "Hello, world!"
            filepath = save_content_to_temp_file(content)
            
            assert os.path.exists(filepath)
            with open(filepath, "r") as f:
                assert f.read() == content
    
    def test_save_with_filename_hint_json(self, tmp_path):
        """Test that filename hint determines extension."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            content = '{"key": "value"}'
            filepath = save_content_to_temp_file(content, filename_hint="data.json")
            
            assert filepath.endswith(".json")
    
    def test_save_with_filename_hint_py(self, tmp_path):
        """Test Python file extension."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            content = "print('hello')"
            filepath = save_content_to_temp_file(content, filename_hint="script.py")
            
            assert filepath.endswith(".py")
    
    def test_save_with_explicit_extension(self, tmp_path):
        """Test explicit extension parameter."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            content = "data"
            filepath = save_content_to_temp_file(content, extension=".csv")
            
            assert filepath.endswith(".csv")
    
    def test_same_content_same_file(self, tmp_path):
        """Test that same content produces same filename (hash-based)."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            content = "Identical content"
            filepath1 = save_content_to_temp_file(content)
            filepath2 = save_content_to_temp_file(content)
            
            assert filepath1 == filepath2


class TestSaveImageToTempFile:
    """Test save_image_to_temp_file function."""
    
    def test_save_jpeg_image(self, tmp_path):
        """Test saving JPEG image from data URL."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            # Create a minimal valid JPEG (just the header bytes for testing)
            # Real JPEG would be larger, but we just need to test the flow
            fake_image = b'\xff\xd8\xff\xe0\x00\x10JFIF'
            data_url = f"data:image/jpeg;base64,{base64.b64encode(fake_image).decode()}"
            
            filepath = save_image_to_temp_file(data_url)
            
            assert filepath is not None
            assert filepath.endswith(".jpg")
            assert os.path.exists(filepath)
    
    def test_save_png_image(self, tmp_path):
        """Test saving PNG image from data URL."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            fake_image = b'\x89PNG\r\n\x1a\n'
            data_url = f"data:image/png;base64,{base64.b64encode(fake_image).decode()}"
            
            filepath = save_image_to_temp_file(data_url)
            
            assert filepath is not None
            assert filepath.endswith(".png")
    
    def test_invalid_data_url(self):
        """Test handling of invalid data URL."""
        filepath = save_image_to_temp_file("not-a-data-url")
        assert filepath is None
    
    def test_invalid_base64(self, tmp_path):
        """Test handling of invalid base64 data."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            filepath = save_image_to_temp_file("data:image/png;base64,not-valid-base64!!!")
            assert filepath is None


# ============================================================================
# CommandBuilder Integration Tests
# ============================================================================

class TestCommandBuilderFileProcessing:
    """Test CommandBuilder file processing methods."""
    
    def test_process_small_content_unchanged(self):
        """Test that small content is returned unchanged."""
        messages = [Message(role="user", content="Short message")]
        builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
        
        result = builder._process_content_part("Short content")
        assert result == "Short content"
    
    def test_process_large_content_saved_to_file(self, tmp_path):
        """Test that large content is saved to temp file."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            messages = [Message(role="user", content="test")]
            builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
            
            # Create content larger than threshold
            large_content = "x" * (CONTENT_SIZE_THRESHOLD + 100)
            result = builder._process_content_part(large_content)
            
            assert result.startswith("@")
            assert tmp_path.as_posix() in result
    
    def test_process_large_content_with_filename(self, tmp_path):
        """Test that large content with filename is properly processed."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            messages = [Message(role="user", content="test")]
            builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
            
            # Content with filename on first line
            large_content = "data.json\n" + "{" + '"key": "value",' * 500 + "}"
            result = builder._process_content_part(large_content)
            
            assert "File 'data.json':" in result
            assert "@" in result
    
    def test_process_image_part_base64(self, tmp_path):
        """Test processing base64 image part."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            messages = [Message(role="user", content="test")]
            builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
            
            fake_image = b'\x89PNG\r\n\x1a\n'
            data_url = f"data:image/png;base64,{base64.b64encode(fake_image).decode()}"
            
            result = builder._process_image_part(data_url)
            
            assert result.startswith("@")
            assert ".png" in result
    
    def test_process_image_part_http_url(self):
        """Test processing HTTP image URL."""
        messages = [Message(role="user", content="test")]
        builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
        
        result = builder._process_image_part("https://example.com/image.jpg")
        
        assert "[Image URL:" in result
        assert "https://example.com/image.jpg" in result
    
    def test_get_processed_content_multimodal(self, tmp_path):
        """Test _get_processed_content with multimodal message."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            msg = Message(
                role="user",
                content=[
                    {"type": "text", "text": "What is this?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(b'PNG').decode()}"}}
                ]
            )
            
            builder = CommandBuilder(model="auto", api_key="sk-test", messages=[msg])
            result = builder._get_processed_content(msg)
            
            assert "What is this?" in result


class TestCommandBuilderMergeMessages:
    """Test CommandBuilder._merge_messages with file content."""
    
    def test_merge_with_small_content(self):
        """Test merging messages with small content."""
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hello")
        ]
        builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
        cmd = builder.build()
        
        prompt = cmd[-1]
        assert "You are helpful." in prompt
        assert "Hello" in prompt

    def test_system_message_large_content_not_saved_to_temp_file(self, tmp_path):
        """System messages (e.g. skills metadata) should never be saved to temp files,
        even when exceeding CONTENT_SIZE_THRESHOLD."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            large_system_content = "<available_skills>" + "x" * (CONTENT_SIZE_THRESHOLD + 500) + "</available_skills>"
            messages = [
                Message(role="system", content=large_system_content),
                Message(role="user", content="Hello")
            ]
            builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
            cmd = builder.build()

            prompt = cmd[-1]
            assert "<available_skills>" in prompt
            assert "</available_skills>" in prompt
            assert "@" not in prompt.split("Hello")[0]

    def test_assistant_message_large_content_not_saved_to_temp_file(self, tmp_path):
        """Assistant messages should not be saved to temp files either."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            large_assistant_content = "Here is a very long response: " + "y" * (CONTENT_SIZE_THRESHOLD + 500)
            messages = [
                Message(role="user", content="Tell me something"),
                Message(role="assistant", content=large_assistant_content),
                Message(role="user", content="Thanks")
            ]
            builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
            cmd = builder.build()

            prompt = cmd[-1]
            assert "Here is a very long response:" in prompt
            assert "@" not in prompt.split("Thanks")[0].split("Tell me something")[1]

    def test_user_message_large_content_still_saved_to_temp_file(self, tmp_path):
        """User messages with large content should still be saved to temp files."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            large_user_content = "data.json\n" + "{" + '"key": "value",' * 500 + "}"
            messages = [
                Message(role="user", content=large_user_content)
            ]
            builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
            cmd = builder.build()

            prompt = cmd[-1]
            assert "@" in prompt
    
    def test_merge_with_multimodal_content(self, tmp_path):
        """Test merging messages with multimodal content."""
        with patch("src.temp_file_handler.CURSOR_CLI_PROXY_TMP", str(tmp_path)):
            messages = [
                Message(
                    role="user",
                    content=[
                        {"type": "text", "text": "Describe this"},
                        {"type": "text", "text": "Additional context"}
                    ]
                )
            ]
            builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
            cmd = builder.build()
            
            prompt = cmd[-1]
            assert "Describe this" in prompt
            assert "Additional context" in prompt
