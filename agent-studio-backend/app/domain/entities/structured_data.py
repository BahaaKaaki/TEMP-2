"""
Domain entities for structured data (CSV/Excel) in knowledge bases.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum


class StructuredTableStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    CREATING = "creating"
    ACTIVE = "active"
    FAILED = "failed"


class RelationshipType(str, Enum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"


class ColumnDataType(str, Enum):
    TEXT = "text"
    INTEGER = "integer"
    NUMERIC = "numeric"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"


@dataclass
class StructuredColumn:
    id: str
    table_id: str
    column_name: str
    display_name: str
    data_type: ColumnDataType
    description: Optional[str] = None
    column_order: int = 0
    nullable: bool = True
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "table_id": self.table_id,
            "column_name": self.column_name,
            "display_name": self.display_name,
            "data_type": self.data_type.value if isinstance(self.data_type, ColumnDataType) else self.data_type,
            "description": self.description,
            "column_order": self.column_order,
            "nullable": self.nullable,
        }


@dataclass
class StructuredTable:
    id: str
    kb_id: str
    document_id: str
    schema_name: str
    table_name: str
    display_name: str
    description: Optional[str] = None
    row_count: int = 0
    source_sheet: Optional[str] = None
    status: StructuredTableStatus = StructuredTableStatus.PENDING_REVIEW
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    columns: List[StructuredColumn] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kb_id": self.kb_id,
            "document_id": self.document_id,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "display_name": self.display_name,
            "description": self.description,
            "row_count": self.row_count,
            "source_sheet": self.source_sheet,
            "status": self.status.value if isinstance(self.status, StructuredTableStatus) else self.status,
            "columns": [c.to_dict() for c in self.columns],
        }


@dataclass
class StructuredRelationship:
    id: str
    kb_id: str
    source_table_id: str
    source_column_id: str
    target_table_id: str
    target_column_id: str
    relationship_type: RelationshipType = RelationshipType.ONE_TO_MANY
    created_at: Optional[datetime] = None
    source_table_name: Optional[str] = None
    source_column_name: Optional[str] = None
    target_table_name: Optional[str] = None
    target_column_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kb_id": self.kb_id,
            "source_table_id": self.source_table_id,
            "source_column_id": self.source_column_id,
            "target_table_id": self.target_table_id,
            "target_column_id": self.target_column_id,
            "relationship_type": self.relationship_type.value if isinstance(self.relationship_type, RelationshipType) else self.relationship_type,
            "source_table_name": self.source_table_name,
            "source_column_name": self.source_column_name,
            "target_table_name": self.target_table_name,
            "target_column_name": self.target_column_name,
        }
