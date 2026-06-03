"""
Text chunking utilities for RAG system.
"""
from typing import List, Optional
from domain.entities.knowledge_base import ChunkingMethod, ChunkingConfig


class TextChunker:
    """Text chunking utilities."""
    
    @staticmethod
    def chunk_text(
        text: str,
        config: ChunkingConfig
    ) -> List[str]:
        """
        Chunk text based on configuration.
        
        Args:
            text: Text to chunk
            config: Chunking configuration
        
        Returns:
            List of text chunks
        """
        if config.method == ChunkingMethod.FIXED_SIZE:
            return TextChunker._fixed_size_chunking(
                text,
                config.chunk_size,
                config.chunk_overlap
            )
        elif config.method == ChunkingMethod.RECURSIVE:
            return TextChunker._recursive_chunking(
                text,
                config.chunk_size,
                config.chunk_overlap,
                config.separators or ["\n\n", "\n", ". ", " ", ""]
            )
        elif config.method == ChunkingMethod.SENTENCE:
            return TextChunker._sentence_chunking(
                text,
                config.chunk_size,
                config.chunk_overlap
            )
        elif config.method == ChunkingMethod.PARAGRAPH:
            return TextChunker._paragraph_chunking(
                text,
                config.chunk_size,
                config.chunk_overlap
            )
        elif config.method == ChunkingMethod.DELIMITER:
            return TextChunker._delimiter_chunking(
                text,
                config.delimiter or "\n\n"
            )
        else:
            return TextChunker._fixed_size_chunking(
                text,
                config.chunk_size,
                config.chunk_overlap
            )
    
    @staticmethod
    def _fixed_size_chunking(
        text: str,
        chunk_size: int,
        chunk_overlap: int
    ) -> List[str]:
        """Fixed-size chunking with overlap."""
        chunks = []
        start = 0
        text_length = len(text)
        
        while start < text_length:
            end = start + chunk_size
            chunk = text[start:end]
            
            if chunk.strip():
                chunks.append(chunk)
            
            start = end - chunk_overlap
            
            if start >= text_length:
                break
        
        return chunks
    
    @staticmethod
    def _recursive_chunking(
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        separators: List[str]
    ) -> List[str]:
        """Recursive chunking using hierarchical separators."""
        if not text or len(text) <= chunk_size:
            return [text] if text.strip() else []
        
        chunks = []
        
        for sep_idx, separator in enumerate(separators):
            if not separator:
                return TextChunker._fixed_size_chunking(text, chunk_size, chunk_overlap)
            if separator in text:
                splits = text.split(separator)
                current_chunk = ""
                remaining_separators = separators[sep_idx + 1:] if sep_idx + 1 < len(separators) else [""]
                
                for i, split in enumerate(splits):
                    if not split.strip():
                        continue
                    
                    test_chunk = current_chunk + (separator if current_chunk else "") + split
                    
                    if len(test_chunk) <= chunk_size:
                        current_chunk = test_chunk
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        
                        if len(split) > chunk_size:
                            sub_chunks = TextChunker._recursive_chunking(
                                split,
                                chunk_size,
                                chunk_overlap,
                                remaining_separators,
                            )
                            chunks.extend(sub_chunks)
                            current_chunk = ""
                        else:
                            current_chunk = split
                
                if current_chunk:
                    chunks.append(current_chunk)
                
                return [c for c in chunks if c.strip()]
        
        return TextChunker._fixed_size_chunking(text, chunk_size, chunk_overlap)
    
    @staticmethod
    def _sentence_chunking(
        text: str,
        chunk_size: int,
        chunk_overlap: int
    ) -> List[str]:
        """Chunk by sentences."""
        import re
        
        sentence_pattern = r'(?<=[.!?])\s+'
        sentences = re.split(sentence_pattern, text)
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if not sentence.strip():
                continue
            
            test_chunk = current_chunk + (" " if current_chunk else "") + sentence
            
            if len(test_chunk) <= chunk_size:
                current_chunk = test_chunk
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                
                if len(sentence) > chunk_size:
                    sub_chunks = TextChunker._fixed_size_chunking(
                        sentence,
                        chunk_size,
                        chunk_overlap
                    )
                    chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    @staticmethod
    def _paragraph_chunking(
        text: str,
        chunk_size: int,
        chunk_overlap: int
    ) -> List[str]:
        """Chunk by paragraphs."""
        paragraphs = text.split('\n\n')
        
        chunks = []
        current_chunk = ""
        
        for paragraph in paragraphs:
            if not paragraph.strip():
                continue
            
            test_chunk = current_chunk + ("\n\n" if current_chunk else "") + paragraph
            
            if len(test_chunk) <= chunk_size:
                current_chunk = test_chunk
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                
                if len(paragraph) > chunk_size:
                    sub_chunks = TextChunker._sentence_chunking(
                        paragraph,
                        chunk_size,
                        chunk_overlap
                    )
                    chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = paragraph
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    @staticmethod
    def _delimiter_chunking(
        text: str,
        delimiter: str
    ) -> List[str]:
        """Split text on a literal delimiter string, keeping each segment as one chunk."""
        if not text or not delimiter:
            return [text] if text and text.strip() else []
        parts = text.split(delimiter)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def validate_config(config: ChunkingConfig) -> tuple[bool, Optional[str]]:
        """
        Validate chunking configuration.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if config.method == ChunkingMethod.DELIMITER:
            if not config.delimiter:
                return False, "delimiter string is required for delimiter chunking"
            return True, None

        if config.method == ChunkingMethod.PAGE:
            return True, None

        if config.method == ChunkingMethod.VISION:
            return True, None

        if config.chunk_size < 1:
            return False, "chunk_size must be greater than 0"
        
        if config.chunk_overlap < 0:
            return False, "chunk_overlap must be non-negative"
        
        if config.chunk_overlap >= config.chunk_size:
            return False, "chunk_overlap must be less than chunk_size"
        
        if config.min_chunk_size and config.min_chunk_size > config.chunk_size:
            return False, "min_chunk_size must be less than or equal to chunk_size"
        
        if config.max_chunk_size and config.max_chunk_size < config.chunk_size:
            return False, "max_chunk_size must be greater than or equal to chunk_size"
        
        return True, None

