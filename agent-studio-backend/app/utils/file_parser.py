"""
File parsing utility using Unstructured library.

Handles parsing of various document types (PDF, TXT, XML, DOCX, CSV, etc.)
and extracts text content for use in chat conversations.
"""

import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# Try to import unstructured - it may not be installed yet
try:
    from unstructured.partition.auto import partition
    UNSTRUCTURED_AVAILABLE = True
except ImportError:
    UNSTRUCTURED_AVAILABLE = False
    logger.warning("Unstructured library not installed. Install with: pip install 'unstructured[all-docs]'")


class FileParser:
    """
    Parser for extracting text and structure from various document types.
    Uses the Unstructured library for intelligent document parsing.
    """
    
    # Supported file types
    SUPPORTED_TYPES = {
        'pdf': 'application/pdf',
        'txt': 'text/plain',
        'xml': 'application/xml',
        'json': 'application/json',
        'csv': 'text/csv',
        'md': 'text/markdown',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'doc': 'application/msword',
        'html': 'text/html',
        'htm': 'text/html',
        'rtf': 'application/rtf',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        # Image types — parsed via the vision OCR pipeline (vision_ocr.py),
        # not by Unstructured. They share the same chat_file row shape so
        # downstream context injection is unchanged.
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'webp': 'image/webp',
        'bmp': 'image/bmp',
    }
    
    # Subset of SUPPORTED_TYPES that must be routed to vision OCR.
    IMAGE_TYPES = frozenset({'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'})
    
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    
    @staticmethod
    def is_supported_file_type(file_extension: str) -> bool:
        """Check if file type is supported."""
        return file_extension.lower().lstrip('.') in FileParser.SUPPORTED_TYPES
    
    @staticmethod
    def is_image_file_type(file_extension: str) -> bool:
        """True if the extension is an image that should be OCR'd via vision LLM."""
        return file_extension.lower().lstrip('.') in FileParser.IMAGE_TYPES
    
    @staticmethod
    def get_mime_type(file_extension: str) -> Optional[str]:
        """Get MIME type for file extension."""
        ext = file_extension.lower().lstrip('.')
        return FileParser.SUPPORTED_TYPES.get(ext)
    
    @staticmethod
    def parse_file(file_path: str) -> Tuple[bool, Optional[str], Optional[List[Dict]], Optional[str]]:
        """
        Parse a file using Unstructured library.
        
        Args:
            file_path: Path to the file to parse
            
        Returns:
            Tuple of (success, extracted_text, parsed_elements, error_message)
            - success: True if parsing succeeded
            - extracted_text: Full text content extracted from document
            - parsed_elements: List of structured elements (JSON-serializable)
            - error_message: Error message if parsing failed
        """
        if not UNSTRUCTURED_AVAILABLE:
            return False, None, None, "Unstructured library not installed. Install with: pip install 'unstructured[all-docs]'"
        
        try:
            path = Path(file_path)
            
            # Check file exists
            if not path.exists():
                return False, None, None, f"File not found: {file_path}"
            
            # Check file size
            file_size = path.stat().st_size
            if file_size > FileParser.MAX_FILE_SIZE:
                return False, None, None, f"File too large: {file_size} bytes (max: {FileParser.MAX_FILE_SIZE})"
            
            # Check file extension
            file_ext = path.suffix.lower().lstrip('.')
            if not FileParser.is_supported_file_type(file_ext):
                return False, None, None, f"Unsupported file type: {file_ext}"
            
            # Images are parsed via the vision OCR pipeline, not Unstructured.
            # FileService dispatches them before reaching this function — if
            # someone calls parse_file directly for an image we return a
            # clear error rather than silently invoking Unstructured (which
            # would either fail or produce an unhelpful caption).
            if FileParser.is_image_file_type(file_ext):
                return False, None, None, (
                    f"Image type '{file_ext}' must be parsed via vision OCR "
                    "(see app.utils.vision_ocr), not FileParser.parse_file."
                )
            
            logger.info("📄 Parsing file: %s (%s, %d bytes)", path.name, file_ext, file_size)
            
            # For JSON and plain-text formats, read raw content directly because
            # the Unstructured JSON partitioner only accepts its own internal schema.
            raw_text_exts = {'json', 'txt', 'md', 'csv'}
            if file_ext in raw_text_exts:
                success, raw_text, read_err = FileParser.parse_simple_text(str(path))
                if success and raw_text:
                    raw_text = raw_text.replace('\x00', '')
                    raw_text = ''.join(
                        c for c in raw_text if ord(c) >= 32 or c in '\n\r\t'
                    )
                    return True, raw_text, [{"type": "RawText", "text": raw_text[:500]}], None
                logger.warning("Raw-text fallback failed for %s: %s", path.name, read_err)

            # Parse the file using Unstructured
            elements = partition(filename=str(path))
            
            # Extract text from elements
            extracted_text_parts = []
            parsed_elements = []
            
            for element in elements:
                # Get text content
                element_text = str(element)
                
                # Sanitize element text (remove null bytes)
                element_text = element_text.replace('\x00', '')
                
                if element_text.strip():
                    extracted_text_parts.append(element_text)
                
                # Create structured element info
                element_dict = {
                    "type": element.__class__.__name__,
                    "text": element_text,
                }
                
                # Add metadata if available
                if hasattr(element, 'metadata'):
                    metadata = element.metadata
                    element_dict["metadata"] = {
                        "page_number": getattr(metadata, 'page_number', None),
                        "filename": getattr(metadata, 'filename', None),
                    }
                
                parsed_elements.append(element_dict)
            
            # Join all text parts
            extracted_text = "\n\n".join(extracted_text_parts)
            
            # Sanitize text: remove null bytes and other invalid characters for PostgreSQL UTF-8
            extracted_text = extracted_text.replace('\x00', '')  # Remove null bytes
            extracted_text = ''.join(char for char in extracted_text if ord(char) >= 32 or char in '\n\r\t')  # Keep only printable chars + newlines/tabs
            
            logger.info("✅ Successfully parsed %s: %d elements, %d chars", path.name, len(elements), len(extracted_text))
            
            return True, extracted_text, parsed_elements, None
            
        except Exception as e:
            error_msg = f"Failed to parse file: {str(e)}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            return False, None, None, error_msg
    
    @staticmethod
    def parse_simple_text(file_path: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Simple text extraction for plain text files (fallback method).
        
        Args:
            file_path: Path to text file
            
        Returns:
            Tuple of (success, text_content, error_message)
        """
        try:
            # Use synchronous I/O here since this entire function runs in asyncio.to_thread
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            logger.info("✅ Read text file: %s (%d chars)", Path(file_path).name, len(text))
            return True, text, None
            
        except UnicodeDecodeError:
            # Try with different encoding
            try:
                with open(file_path, 'r', encoding='latin-1') as f:
                    text = f.read()
                return True, text, None
            except Exception as e:
                return False, None, f"Failed to read file: {str(e)}"
        except Exception as e:
            return False, None, f"Failed to read file: {str(e)}"
    
    # File types where Unstructured provides page_number metadata
    PAGE_AWARE_TYPES = {'pdf', 'docx', 'doc', 'pptx', 'rtf', 'html', 'htm', 'xml'}

    @staticmethod
    def supports_page_chunking(file_name: str) -> bool:
        """Check if the file type supports native page-based chunking."""
        ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
        return ext in FileParser.PAGE_AWARE_TYPES

    @staticmethod
    def group_elements_by_page(parsed_elements: Optional[List[Dict]]) -> List[str]:
        """
        Group parsed elements by page number and return one text chunk per page.
        Works for PDFs (real pages), DOCX/PPTX (page/slide breaks detected by
        Unstructured), and other formats where page_number metadata is available.

        Elements without a page_number are appended to the last known page.

        Returns:
            List of page texts, ordered by page number.
        """
        if not parsed_elements:
            return []

        from collections import OrderedDict
        pages: OrderedDict[int, List[str]] = OrderedDict()
        current_page = 1

        for elem in parsed_elements:
            text = (elem.get("text") or "").strip()
            if not text:
                continue

            page_num = None
            meta = elem.get("metadata")
            if isinstance(meta, dict):
                page_num = meta.get("page_number")

            if page_num is not None:
                current_page = page_num
            pages.setdefault(current_page, []).append(text)

        return ["\n\n".join(parts) for parts in pages.values() if parts]

    @staticmethod
    def group_elements_by_page_with_numbers(
        parsed_elements: Optional[List[Dict]],
    ) -> List[Tuple[int, str]]:
        """Like ``group_elements_by_page`` but keeps each page's page_number.

        Returns a list of ``(page_number, page_text)`` pairs ordered by page so
        callers can align page text with rendered page images for citations.
        """
        if not parsed_elements:
            return []

        from collections import OrderedDict
        pages: "OrderedDict[int, List[str]]" = OrderedDict()
        current_page = 1

        for elem in parsed_elements:
            text = (elem.get("text") or "").strip()
            if not text:
                continue
            meta = elem.get("metadata")
            page_num = meta.get("page_number") if isinstance(meta, dict) else None
            if page_num is not None:
                current_page = page_num
            pages.setdefault(current_page, []).append(text)

        return [(pn, "\n\n".join(parts)) for pn, parts in pages.items() if parts]

    @staticmethod
    def get_text_preview(text: str, max_length: int = 500) -> str:
        """
        Get a preview of extracted text.
        
        Args:
            text: Full text content
            max_length: Maximum length of preview
            
        Returns:
            Preview string
        """
        if not text:
            return ""
        
        if len(text) <= max_length:
            return text
        
        return text[:max_length] + "..."


# Convenience function for quick parsing
def parse_document(file_path: str) -> Dict:
    """
    Parse a document and return results in a dict.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Dict with keys: success, extracted_text, parsed_elements, error
    """
    success, text, elements, error = FileParser.parse_file(file_path)
    
    return {
        "success": success,
        "extracted_text": text,
        "parsed_elements": elements,
        "error": error,
        "preview": FileParser.get_text_preview(text) if text else None
    }

