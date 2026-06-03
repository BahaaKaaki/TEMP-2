"""
Knowledge Base domain entity for RAG system.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class ChunkingMethod(str, Enum):
    """Chunking strategy enumeration."""
    FIXED_SIZE = "fixed_size"
    SEMANTIC = "semantic"
    RECURSIVE = "recursive"
    SENTENCE = "sentence"
    PARAGRAPH = "paragraph"
    DELIMITER = "delimiter"
    PAGE = "page"
    VISION = "vision"


class EmbeddingModel(str, Enum):
    """Embedding model enumeration.

    Single source of truth for enum value -> proxy API model ID and vector
    dimension.  Every consumer should call the helper methods below instead
    of maintaining its own mapping dictionary.
    """
    # Azure models (via GenAI proxy)
    AZURE_ADA_002 = "azure_ada_002"
    AZURE_SMALL = "azure_small"
    AZURE_LARGE = "azure_large"

    # Vertex AI models (via GenAI proxy)
    VERTEX_EMBEDDING_001 = "vertex_embedding_001"
    VERTEX_EMBEDDING_005 = "vertex_embedding_005"
    VERTEX_GEMINI_EMBEDDING = "vertex_gemini_embedding"

    # AWS Bedrock models (via GenAI proxy)
    BEDROCK_TITAN_V1 = "bedrock_titan_v1"
    BEDROCK_TITAN_V2 = "bedrock_titan_v2"

    # Legacy OpenAI (direct connection)
    OPENAI_ADA_002 = "openai_ada_002"
    OPENAI_SMALL = "openai_small"
    OPENAI_LARGE = "openai_large"

    # ------------------------------------------------------------------
    # Centralised look-up tables — update ONLY here when adding models.
    # ------------------------------------------------------------------

    @property
    def api_model_id(self) -> str:
        """Return the GenAI-proxy (or direct-provider) model ID string."""
        return _MODEL_API_IDS[self]

    @property
    def dimension(self) -> int:
        """Return the vector dimension produced by this model."""
        return _MODEL_DIMENSIONS[self]

    @classmethod
    def from_value_or_default(cls, raw: str, default: "EmbeddingModel | None" = None) -> "EmbeddingModel":
        """Resolve a raw string to an enum member, falling back to *default*."""
        try:
            return cls(raw)
        except ValueError:
            if default is not None:
                return default
            return cls.AZURE_ADA_002


# Kept outside the enum body so the members are already defined.
_MODEL_API_IDS: dict["EmbeddingModel", str] = {
    EmbeddingModel.AZURE_ADA_002:          "azure.text-embedding-ada-002",
    # EmbeddingModel.AZURE_SMALL:            "azure.text-embedding-3-small",
    # EmbeddingModel.AZURE_LARGE:            "azure.text-embedding-3-large",
    # EmbeddingModel.VERTEX_EMBEDDING_001:   "vertex_ai.gemini-embedding-001",
    # EmbeddingModel.VERTEX_EMBEDDING_005:   "vertex_ai.text-embedding-005",
    # EmbeddingModel.VERTEX_GEMINI_EMBEDDING:"vertex_ai.gemini-embedding",
    # EmbeddingModel.BEDROCK_TITAN_V1:       "bedrock.amazon.titan-embed-text-v1",
    # EmbeddingModel.BEDROCK_TITAN_V2:       "bedrock.amazon.titan-embed-text-v2",
    # EmbeddingModel.OPENAI_ADA_002:         "text-embedding-ada-002",
    # EmbeddingModel.OPENAI_SMALL:           "text-embedding-3-small",
    # EmbeddingModel.OPENAI_LARGE:           "text-embedding-3-large",
}

_MODEL_DIMENSIONS: dict["EmbeddingModel", int] = {
    EmbeddingModel.AZURE_ADA_002:          1536,
    # EmbeddingModel.AZURE_SMALL:            1536,
    # EmbeddingModel.AZURE_LARGE:            3072,
    # EmbeddingModel.VERTEX_EMBEDDING_001:   768,
    # EmbeddingModel.VERTEX_EMBEDDING_005:   768,
    # EmbeddingModel.VERTEX_GEMINI_EMBEDDING:768,
    # EmbeddingModel.BEDROCK_TITAN_V1:       1536,
    # EmbeddingModel.BEDROCK_TITAN_V2:       1024,
    # EmbeddingModel.OPENAI_ADA_002:         1536,
    # EmbeddingModel.OPENAI_SMALL:           1536,
    # EmbeddingModel.OPENAI_LARGE:           3072,
}


class SearchMethod(str, Enum):
    """Search methods for RAG retrieval."""
    SEMANTIC = "semantic"  # Pure vector similarity
    BM25 = "bm25"  # Keyword-based full-text search
    HYBRID = "hybrid"  # Semantic + BM25 with RRF fusion


class RerankerModel(str, Enum):
    """Reranking models for improving search results."""
    NONE = "none"  # No reranking
    MINILM = "cross-encoder/ms-marco-MiniLM-L-6-v2"  # Fast, lightweight
    BGE_RERANKER = "BAAI/bge-reranker-base"  # Better quality, slower


class KnowledgeBaseStatus(str, Enum):
    """Knowledge base status."""
    CREATING = "creating"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETING = "deleting"
    FAILED = "failed"


class MetadataFieldType(str, Enum):
    """Supported data types for KB metadata fields."""
    STRING = "string"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"


class MetadataFieldScope(str, Enum):
    """Scope of metadata inference: whole document vs. per-chunk."""
    GLOBAL = "global"
    LOCAL = "local"


@dataclass
class MetadataFieldDef:
    """Definition of a single metadata field on a knowledge base."""
    name: str
    type: MetadataFieldType
    scope: MetadataFieldScope
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "scope": self.scope.value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetadataFieldDef":
        return cls(
            name=data["name"],
            type=MetadataFieldType(data["type"]),
            scope=MetadataFieldScope(data["scope"]),
            description=data.get("description"),
        )


@dataclass
class ChunkingConfig:
    """Configuration for document chunking."""
    method: ChunkingMethod
    chunk_size: int
    chunk_overlap: int
    separators: Optional[list] = None
    delimiter: Optional[str] = None
    min_chunk_size: Optional[int] = None
    max_chunk_size: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "method": self.method.value,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "separators": self.separators,
            "delimiter": self.delimiter,
            "min_chunk_size": self.min_chunk_size,
            "max_chunk_size": self.max_chunk_size,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkingConfig":
        """Create from dictionary."""
        return cls(
            method=ChunkingMethod(data["method"]),
            chunk_size=data["chunk_size"],
            chunk_overlap=data["chunk_overlap"],
            separators=data.get("separators"),
            delimiter=data.get("delimiter"),
            min_chunk_size=data.get("min_chunk_size"),
            max_chunk_size=data.get("max_chunk_size"),
        )


@dataclass
class KnowledgeBase:
    """Knowledge Base domain entity."""
    
    id: str
    session_id: str
    name: str
    description: Optional[str]
    azure_folder_path: str
    chunk_table_name: str
    chunking_config: ChunkingConfig
    embedding_model: EmbeddingModel
    vector_dimension: int
    status: KnowledgeBaseStatus
    document_count: int
    chunk_count: int
    total_size_bytes: int
    metadata: Optional[Dict[str, Any]]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    metadata_schema: Optional[List[MetadataFieldDef]] = field(default=None)
    has_structured_data: bool = False
    is_pinned: bool = False
    last_accessed_at: Optional[datetime] = None
    is_public: bool = False
    
    def is_active(self) -> bool:
        """Check if KB is active."""
        return self.status == KnowledgeBaseStatus.ACTIVE
    
    def is_creating(self) -> bool:
        """Check if KB is being created."""
        return self.status == KnowledgeBaseStatus.CREATING
    
    def is_deleted(self) -> bool:
        """Check if KB is soft-deleted."""
        return self.deleted_at is not None
    
    def can_add_documents(self) -> bool:
        """Check if documents can be added."""
        return self.status == KnowledgeBaseStatus.ACTIVE
    
    def get_total_size_mb(self) -> float:
        """Get total size in MB."""
        return self.total_size_bytes / (1024 * 1024)
    
    def mark_as_active(self) -> None:
        """Mark KB as active."""
        self.status = KnowledgeBaseStatus.ACTIVE
        self.updated_at = datetime.utcnow()
    
    def mark_as_failed(self) -> None:
        """Mark KB creation as failed."""
        self.status = KnowledgeBaseStatus.FAILED
        self.updated_at = datetime.utcnow()
    
    def increment_document_count(self) -> None:
        """Increment document count."""
        self.document_count += 1
        self.updated_at = datetime.utcnow()
    
    def increment_chunk_count(self, count: int) -> None:
        """Increment chunk count."""
        self.chunk_count += count
        self.updated_at = datetime.utcnow()
    
    def add_size(self, size_bytes: int) -> None:
        """Add to total size."""
        self.total_size_bytes += size_bytes
        self.updated_at = datetime.utcnow()


@dataclass
class DocumentChunk:
    """Document chunk entity."""
    
    id: str
    kb_id: str
    document_id: str
    chunk_index: int
    chunk_text: str
    chunk_size: int
    created_at: datetime
    document_title: Optional[str] = None  # For BM25 search enhancement
    embedding: Optional[list] = None
    embedding_status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def is_embedded(self) -> bool:
        """Check if chunk is embedded."""
        return self.embedding is not None and len(self.embedding) > 0
    
    def get_preview(self, length: int = 100) -> str:
        """Get text preview."""
        if len(self.chunk_text) <= length:
            return self.chunk_text
        return self.chunk_text[:length] + "..."

