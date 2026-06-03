"""
Repository for managing per-KB PostgreSQL schemas and structured data tables (CSV/Excel uploads).
"""
import asyncio
import logging
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import StructuredColumnEntity, StructuredTableEntity, StructuredRelationshipEntity
from domain.entities.structured_data import (
    ColumnDataType,
    RelationshipType,
    StructuredColumn,
    StructuredRelationship,
    StructuredTable,
    StructuredTableStatus,
)

logger = logging.getLogger(__name__)

# Map ColumnDataType to PostgreSQL types
_COLUMN_TYPE_MAP = {
    ColumnDataType.TEXT: "TEXT",
    ColumnDataType.INTEGER: "BIGINT",
    ColumnDataType.NUMERIC: "NUMERIC",
    ColumnDataType.DATE: "DATE",
    ColumnDataType.DATETIME: "TIMESTAMP",
    ColumnDataType.BOOLEAN: "BOOLEAN",
}

MAX_PARAMS_PER_QUERY = 10000
DEFAULT_BATCH_SIZE = 1000


def _sanitize_name(name: str) -> str:
    """Keep only alphanumeric and underscores, lowercased, max 63 chars."""
    if not name:
        return ""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(name)).lower()
    return sanitized[:63]


class StructuredDataRepository:
    """Repository for structured data tables and per-KB schemas."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_schema(self, schema_name: str) -> None:
        """CREATE SCHEMA IF NOT EXISTS."""
        safe_schema = _sanitize_name(schema_name)
        if not safe_schema:
            raise ValueError("Invalid schema name")
        await self.db.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{safe_schema}"'))

    async def drop_schema(self, schema_name: str) -> None:
        """DROP SCHEMA CASCADE."""
        safe_schema = _sanitize_name(schema_name)
        if not safe_schema:
            raise ValueError("Invalid schema name")
        await self.db.execute(text(f'DROP SCHEMA IF EXISTS "{safe_schema}" CASCADE'))

    async def create_data_table(
        self,
        schema_name: str,
        table_name: str,
        columns: List[StructuredColumn],
    ) -> None:
        """CREATE TABLE in the given schema with typed columns."""
        safe_schema = _sanitize_name(schema_name)
        safe_table = _sanitize_name(table_name)
        if not safe_schema or not safe_table:
            raise ValueError("Invalid schema or table name")

        col_defs = []
        for col in sorted(columns, key=lambda c: c.column_order):
            safe_col = _sanitize_name(col.column_name)
            if not safe_col:
                continue
            pg_type = _COLUMN_TYPE_MAP.get(
                col.data_type if isinstance(col.data_type, ColumnDataType) else ColumnDataType(col.data_type),
                "TEXT",
            )
            col_defs.append(f'"{safe_col}" {pg_type} NULL')

        if not col_defs:
            raise ValueError("At least one column required")

        await self.db.execute(text(f'DROP TABLE IF EXISTS "{safe_schema}"."{safe_table}"'))
        create_sql = f'CREATE TABLE "{safe_schema}"."{safe_table}" ({", ".join(col_defs)})'
        await self.db.execute(text(create_sql))

    # Values treated as NULL during casting — must stay in sync with
    # schema_inference._is_empty so type-inference and insertion agree.
    _NULL_LITERALS = frozenset({"", "null", "none", "na", "n/a", "-", "—", "–"})

    def _is_null_literal(self, val) -> bool:
        if val is None:
            return True
        return str(val).strip().lower() in self._NULL_LITERALS

    def _cast_value(self, val: str, col_type: str):
        """Cast string value to proper Python type for asyncpg INSERT."""
        if self._is_null_literal(val):
            return None
        s = str(val).strip()
        if not s:
            return None

        if col_type == "integer":
            try:
                return int(float(s.replace(",", "")))
            except (ValueError, OverflowError):
                return None

        if col_type == "numeric":
            try:
                return float(s.replace(",", ""))
            except (ValueError, OverflowError):
                return None

        if col_type == "date":
            from dateutil import parser as dateutil_parser
            try:
                return dateutil_parser.parse(s).date()
            except (ValueError, OverflowError):
                return None

        if col_type == "datetime":
            from dateutil import parser as dateutil_parser
            try:
                return dateutil_parser.parse(s)
            except (ValueError, OverflowError):
                return None

        if col_type == "boolean":
            v = s.lower()
            if v in ("true", "1", "yes"):
                return True
            if v in ("false", "0", "no"):
                return False
            return None

        return val

    def validate_data_sample(
        self,
        headers: List[str],
        rows: List[List[str]],
        column_types: Dict[str, str],
        sample_size: int = 50,
    ) -> List[str]:
        """Check a sample of rows for type-casting issues. Returns a list of warning strings."""
        warnings = []
        sample = rows[:sample_size]
        type_fail_counts: Dict[str, int] = {}

        for row_idx, row in enumerate(sample):
            for col_idx, h in enumerate(headers):
                if col_idx >= len(row):
                    continue
                val = row[col_idx]
                if self._is_null_literal(val):
                    continue
                col_type = column_types.get(h, "text")
                if col_type == "text":
                    continue
                cast_result = self._cast_value(val, col_type)
                if cast_result is None:
                    key = f"{h} ({col_type})"
                    type_fail_counts[key] = type_fail_counts.get(key, 0) + 1

        for col_key, count in type_fail_counts.items():
            pct = count / len(sample) * 100
            if pct > 30:
                warnings.append(
                    f"Column '{col_key}': {count}/{len(sample)} sampled values "
                    f"({pct:.0f}%) could not be cast and will become NULL. "
                    f"Consider changing the data type to 'text'."
                )
        return warnings

    def _prepare_batch(
        self,
        batch: List[List[str]],
        orig_headers: List[str],
        safe_headers: List[str],
        column_types: Dict[str, str],
        safe_schema: str,
        safe_table: str,
        col_list: str,
    ) -> tuple:
        """Synchronous: cast values and build SQL + params for one batch. Runs in a thread."""
        value_clauses = []
        all_params = {}
        for row_idx, row in enumerate(batch):
            placeholders = []
            for j, (orig_h, safe_h) in enumerate(zip(orig_headers, safe_headers)):
                val = row[j] if j < len(row) else ""
                col_type = column_types.get(orig_h, "text")
                cast_val = self._cast_value(val, col_type)
                param_name = f"r{row_idx}_{safe_h}"
                placeholders.append(f":{param_name}")
                all_params[param_name] = cast_val
            value_clauses.append(f"({', '.join(placeholders)})")
        sql_str = f'INSERT INTO "{safe_schema}"."{safe_table}" ({col_list}) VALUES {", ".join(value_clauses)}'
        return sql_str, all_params

    async def insert_rows(
        self,
        schema_name: str,
        table_name: str,
        headers: List[str],
        rows: List[List[str]],
        column_types: Dict[str, str],
    ) -> int:
        """Bulk INSERT rows with proper type casting. Batch size is dynamic based on column count.
        Returns the number of rows inserted and a list of per-row errors (if any)."""
        safe_schema = _sanitize_name(schema_name)
        safe_table = _sanitize_name(table_name)
        if not safe_schema or not safe_table:
            raise ValueError("Invalid schema or table name")

        header_pairs = [(h, _sanitize_name(h)) for h in headers if _sanitize_name(h)]
        if not header_pairs:
            raise ValueError("No valid column headers")
        orig_headers, safe_headers = zip(*header_pairs)
        orig_headers = list(orig_headers)
        safe_headers = list(safe_headers)

        col_list = ", ".join(f'"{h}"' for h in safe_headers)
        num_cols = len(safe_headers)
        batch_size = max(1, min(DEFAULT_BATCH_SIZE, MAX_PARAMS_PER_QUERY // num_cols))
        logger.info(
            "insert_rows: %d rows, %d cols → batch_size=%d",
            len(rows), num_cols, batch_size,
        )

        inserted = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            sql_str, all_params = await asyncio.to_thread(
                self._prepare_batch,
                batch, orig_headers, safe_headers, column_types,
                safe_schema, safe_table, col_list,
            )
            await self.db.execute(text(sql_str), all_params)
            inserted += len(batch)
        return inserted

    async def drop_data_table(self, schema_name: str, table_name: str) -> None:
        """DROP TABLE IF EXISTS."""
        safe_schema = _sanitize_name(schema_name)
        safe_table = _sanitize_name(table_name)
        if not safe_schema or not safe_table:
            raise ValueError("Invalid schema or table name")
        await self.db.execute(text(f'DROP TABLE IF EXISTS "{safe_schema}"."{safe_table}"'))

    async def execute_query(
        self,
        schema_name: str,
        sql: str,
        params: Optional[Dict] = None,
        timeout_seconds: int = 30,
        max_rows: int = 100,
    ) -> List[Dict]:
        """Execute a SELECT query within the schema. Returns list of dicts (column_name -> value)."""
        sql_stripped = sql.strip().upper()
        if not sql_stripped.startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")

        safe_schema = _sanitize_name(schema_name)
        if not safe_schema:
            raise ValueError("Invalid schema name")

        # Enforce max_rows by wrapping in subquery
        sql_clean = sql.strip().rstrip(";")
        limited_sql = f"SELECT * FROM ({sql_clean}) AS _sub LIMIT {max_rows}"

        timeout_seconds = max(1, min(timeout_seconds, 120))
        await self.db.execute(text(f'SET search_path TO "{safe_schema}"'))
        await self.db.execute(text(f"SET statement_timeout = '{timeout_seconds}s'"))

        result = await self.db.execute(text(limited_sql), params or {})
        rows = result.fetchall()
        columns = result.keys()

        return [dict(zip(columns, row)) for row in rows]

    async def save_table_metadata(self, table: StructuredTable) -> StructuredTable:
        """Insert into structured_table, return domain entity."""
        entity = StructuredTableEntity(
            id=table.id or str(uuid.uuid4()),
            kbId=table.kb_id,
            documentId=table.document_id,
            schemaName=table.schema_name,
            tableName=table.table_name,
            displayName=table.display_name,
            description=table.description,
            rowCount=table.row_count,
            sourceSheet=table.source_sheet,
            status=table.status.value if isinstance(table.status, StructuredTableStatus) else table.status,
            createdBy=table.created_by,
        )
        self.db.add(entity)
        await self.db.flush()

        return StructuredTable(
            id=entity.id,
            kb_id=entity.kbId,
            document_id=entity.documentId,
            schema_name=entity.schemaName,
            table_name=entity.tableName,
            display_name=entity.displayName,
            description=entity.description,
            row_count=entity.rowCount,
            source_sheet=entity.sourceSheet,
            status=StructuredTableStatus(entity.status),
            created_by=entity.createdBy,
            created_at=entity.createdAt,
            updated_at=entity.updatedAt,
            columns=table.columns,
        )

    async def save_column_metadata(self, columns: List[StructuredColumn]) -> None:
        """Bulk insert into structured_column."""
        for col in columns:
            entity = StructuredColumnEntity(
                id=col.id or str(uuid.uuid4()),
                tableId=col.table_id,
                columnName=col.column_name,
                displayName=col.display_name,
                dataType=col.data_type.value if isinstance(col.data_type, ColumnDataType) else col.data_type,
                description=col.description,
                columnOrder=col.column_order,
                nullable=col.nullable,
            )
            self.db.add(entity)
        await self.db.flush()

    async def update_column_description(
        self, column_id: str, description: Optional[str]
    ) -> Optional[StructuredColumn]:
        """Update the semantic description on a single column.

        Returns the updated domain entity, or ``None`` if the column does
        not exist.  The column's KB is resolved via its parent table so
        the caller can enforce RLS / ownership checks before calling this.
        """
        query = select(StructuredColumnEntity).where(
            StructuredColumnEntity.id == column_id
        )
        result = await self.db.execute(query)
        entity = result.scalar_one_or_none()
        if not entity:
            return None

        entity.description = description
        await self.db.flush()

        return StructuredColumn(
            id=entity.id,
            table_id=entity.tableId,
            column_name=entity.columnName,
            display_name=entity.displayName,
            data_type=ColumnDataType(entity.dataType),
            description=entity.description,
            column_order=entity.columnOrder,
            nullable=entity.nullable,
            created_at=entity.createdAt,
        )

    async def get_column_kb_id(self, column_id: str) -> Optional[str]:
        """Return the KB ID that owns the given column (via its parent
        table), or ``None`` if the column cannot be found."""
        result = await self.db.execute(
            select(StructuredTableEntity.kbId)
            .join(
                StructuredColumnEntity,
                StructuredColumnEntity.tableId == StructuredTableEntity.id,
            )
            .where(StructuredColumnEntity.id == column_id)
        )
        row = result.first()
        return row[0] if row else None

    async def get_table_names_for_kb(self, kb_id: str) -> set:
        """Return set of existing table names (lowercase) for a KB."""
        result = await self.db.execute(
            select(StructuredTableEntity.tableName).where(
                StructuredTableEntity.kbId == kb_id
            )
        )
        return {row[0].lower() for row in result.fetchall()}

    async def get_tables_for_kb(self, kb_id: str) -> List[StructuredTable]:
        """Get all structured tables for a KB, including their columns."""
        tables_query = select(StructuredTableEntity).where(
            StructuredTableEntity.kbId == kb_id
        )
        tables_result = await self.db.execute(tables_query)
        table_entities = tables_result.scalars().all()

        columns_query = select(StructuredColumnEntity).where(
            StructuredColumnEntity.tableId.in_([t.id for t in table_entities])
        ).order_by(StructuredColumnEntity.columnOrder, StructuredColumnEntity.columnName)
        columns_result = await self.db.execute(columns_query)
        column_entities = columns_result.scalars().all()

        columns_by_table: Dict[str, List[StructuredColumn]] = {}
        for c in column_entities:
            cols = columns_by_table.setdefault(c.tableId, [])
            cols.append(
                StructuredColumn(
                    id=c.id,
                    table_id=c.tableId,
                    column_name=c.columnName,
                    display_name=c.displayName,
                    data_type=ColumnDataType(c.dataType),
                    description=c.description,
                    column_order=c.columnOrder,
                    nullable=c.nullable,
                    created_at=c.createdAt,
                )
            )

        return [
            StructuredTable(
                id=t.id,
                kb_id=t.kbId,
                document_id=t.documentId,
                schema_name=t.schemaName,
                table_name=t.tableName,
                display_name=t.displayName,
                description=t.description,
                row_count=t.rowCount,
                source_sheet=t.sourceSheet,
                status=StructuredTableStatus(t.status),
                created_by=t.createdBy,
                created_at=t.createdAt,
                updated_at=t.updatedAt,
                columns=columns_by_table.get(t.id, []),
            )
            for t in table_entities
        ]

    async def get_table_by_id(self, table_id: str) -> Optional[StructuredTable]:
        """Get structured table by ID."""
        query = select(StructuredTableEntity).where(
            StructuredTableEntity.id == table_id
        )
        result = await self.db.execute(query)
        entity = result.scalar_one_or_none()
        if not entity:
            return None

        columns_query = select(StructuredColumnEntity).where(
            StructuredColumnEntity.tableId == entity.id
        ).order_by(StructuredColumnEntity.columnOrder, StructuredColumnEntity.columnName)
        cols_result = await self.db.execute(columns_query)
        column_entities = cols_result.scalars().all()

        columns = [
            StructuredColumn(
                id=c.id,
                table_id=c.tableId,
                column_name=c.columnName,
                display_name=c.displayName,
                data_type=ColumnDataType(c.dataType),
                description=c.description,
                column_order=c.columnOrder,
                nullable=c.nullable,
                created_at=c.createdAt,
            )
            for c in column_entities
        ]

        return StructuredTable(
            id=entity.id,
            kb_id=entity.kbId,
            document_id=entity.documentId,
            schema_name=entity.schemaName,
            table_name=entity.tableName,
            display_name=entity.displayName,
            description=entity.description,
            row_count=entity.rowCount,
            source_sheet=entity.sourceSheet,
            status=StructuredTableStatus(entity.status),
            created_by=entity.createdBy,
            created_at=entity.createdAt,
            updated_at=entity.updatedAt,
            columns=columns,
        )

    async def get_table_by_document(self, document_id: str) -> Optional[StructuredTable]:
        """Get first structured table for a specific document (for single-table docs)."""
        tables = await self.get_all_tables_for_document(document_id)
        return tables[0] if tables else None

    async def get_all_tables_for_document(self, document_id: str) -> list:
        """Get all structured tables for a document (supports multi-sheet Excel)."""
        query = select(StructuredTableEntity).where(
            StructuredTableEntity.documentId == document_id
        ).order_by(StructuredTableEntity.createdAt)
        result = await self.db.execute(query)
        entities = result.scalars().all()
        if not entities:
            return []

        tables = []
        for entity in entities:
            columns_query = select(StructuredColumnEntity).where(
                StructuredColumnEntity.tableId == entity.id
            ).order_by(StructuredColumnEntity.columnOrder, StructuredColumnEntity.columnName)
            cols_result = await self.db.execute(columns_query)
            column_entities = cols_result.scalars().all()

            columns = [
                StructuredColumn(
                    id=c.id,
                    table_id=c.tableId,
                    column_name=c.columnName,
                    display_name=c.displayName,
                    data_type=ColumnDataType(c.dataType),
                    description=c.description,
                    column_order=c.columnOrder,
                    nullable=c.nullable,
                    created_at=c.createdAt,
                )
                for c in column_entities
            ]

            tables.append(StructuredTable(
                id=entity.id,
                kb_id=entity.kbId,
                document_id=entity.documentId,
                schema_name=entity.schemaName,
                table_name=entity.tableName,
                display_name=entity.displayName,
                description=entity.description,
                row_count=entity.rowCount,
                source_sheet=entity.sourceSheet,
                status=StructuredTableStatus(entity.status),
                created_by=entity.createdBy,
                created_at=entity.createdAt,
                updated_at=entity.updatedAt,
                columns=columns,
            ))

        return tables

    async def update_table_status(
        self,
        table_id: str,
        status: StructuredTableStatus,
        row_count: Optional[int] = None,
    ) -> None:
        """Update status and optionally row_count."""
        if row_count is not None:
            await self.db.execute(
                text("""
                    UPDATE structured_table
                    SET status = :status, row_count = :row_count, updated_at = :updated_at
                    WHERE id = :table_id
                """),
                {
                    "table_id": table_id,
                    "status": status.value,
                    "row_count": row_count,
                    "updated_at": datetime.utcnow(),
                },
            )
        else:
            await self.db.execute(
                text("""
                    UPDATE structured_table
                    SET status = :status, updated_at = :updated_at
                    WHERE id = :table_id
                """),
                {
                    "table_id": table_id,
                    "status": status.value,
                    "updated_at": datetime.utcnow(),
                },
            )

    async def delete_tables_for_document(self, document_id: str) -> None:
        """Delete structured_table and structured_column metadata for a document."""
        await self.db.execute(
            text("DELETE FROM structured_table WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )

    async def drop_tables_for_document(self, document_id: str) -> None:
        """DROP actual PG data tables and delete metadata for a document."""
        query = select(
            StructuredTableEntity.schemaName, StructuredTableEntity.tableName
        ).where(StructuredTableEntity.documentId == document_id)
        result = await self.db.execute(query)
        pairs = result.fetchall()

        for schema_name, table_name in pairs:
            safe_schema = _sanitize_name(schema_name)
            safe_table = _sanitize_name(table_name)
            if safe_schema and safe_table:
                await self.db.execute(
                    text(f'DROP TABLE IF EXISTS "{safe_schema}"."{safe_table}"')
                )

        if pairs:
            await self.db.execute(
                text("DELETE FROM structured_table WHERE document_id = :doc_id"),
                {"doc_id": document_id},
            )

    async def update_kb_structured_flag(self, kb_id: str, has_structured: bool) -> None:
        """UPDATE knowledge_base SET hasStructuredData = :flag WHERE id = :kb_id."""
        await self.db.execute(
            text('UPDATE knowledge_base SET "hasStructuredData" = :flag WHERE id = :kb_id'),
            {"flag": has_structured, "kb_id": kb_id},
        )

    async def get_table_preview(
        self,
        schema_name: str,
        table_name: str,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict:
        """SELECT * with pagination from the actual data table."""
        safe_schema = _sanitize_name(schema_name)
        safe_table = _sanitize_name(table_name)
        if not safe_schema or not safe_table:
            raise ValueError("Invalid schema or table name")

        offset = (page - 1) * page_size

        count_sql = text(
            f'SELECT COUNT(*) FROM "{safe_schema}"."{safe_table}"'
        )
        count_result = await self.db.execute(count_sql)
        total_rows = count_result.scalar() or 0

        data_sql = text(
            f'SELECT * FROM "{safe_schema}"."{safe_table}" LIMIT :limit OFFSET :offset'
        )
        data_result = await self.db.execute(data_sql, {"limit": page_size, "offset": offset})
        rows_raw = data_result.fetchall()
        rows = [list(row) for row in rows_raw]

        total_pages = (total_rows + page_size - 1) // page_size if page_size > 0 else 0

        return {
            "rows": rows,
            "total_rows": total_rows,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # ------------------------------------------------------------------
    # Relationship CRUD
    # ------------------------------------------------------------------

    async def save_relationship(self, rel: StructuredRelationship) -> StructuredRelationship:
        """Insert a relationship. Validates no many-to-many and no self-table links."""
        if rel.source_table_id == rel.target_table_id:
            raise ValueError("Cannot create a relationship between columns of the same table")

        existing = await self.db.execute(
            select(StructuredRelationshipEntity).where(
                StructuredRelationshipEntity.sourceColumnId == rel.source_column_id,
                StructuredRelationshipEntity.targetColumnId == rel.target_column_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("This relationship already exists")

        entity = StructuredRelationshipEntity(
            id=rel.id or str(uuid.uuid4()),
            kbId=rel.kb_id,
            sourceTableId=rel.source_table_id,
            sourceColumnId=rel.source_column_id,
            targetTableId=rel.target_table_id,
            targetColumnId=rel.target_column_id,
            relationshipType=rel.relationship_type.value if isinstance(rel.relationship_type, RelationshipType) else rel.relationship_type,
        )
        self.db.add(entity)
        await self.db.flush()
        rel.id = entity.id
        rel.created_at = entity.createdAt
        return rel

    async def get_relationships_for_kb(self, kb_id: str) -> List[StructuredRelationship]:
        """Return all relationships for a KB with resolved table/column names."""
        query = text("""
            SELECT
                r.id, r.kb_id,
                r.source_table_id, r.source_column_id,
                r.target_table_id, r.target_column_id,
                r.relationship_type, r.created_at,
                st.table_name  AS source_table_name,
                sc.column_name AS source_column_name,
                tt.table_name  AS target_table_name,
                tc.column_name AS target_column_name
            FROM structured_relationship r
            JOIN structured_table  st ON st.id = r.source_table_id
            JOIN structured_column sc ON sc.id = r.source_column_id
            JOIN structured_table  tt ON tt.id = r.target_table_id
            JOIN structured_column tc ON tc.id = r.target_column_id
            WHERE r.kb_id = :kb_id
            ORDER BY r.created_at
        """)
        result = await self.db.execute(query, {"kb_id": kb_id})
        rows = result.fetchall()
        return [
            StructuredRelationship(
                id=row[0],
                kb_id=row[1],
                source_table_id=row[2],
                source_column_id=row[3],
                target_table_id=row[4],
                target_column_id=row[5],
                relationship_type=RelationshipType(row[6]),
                created_at=row[7],
                source_table_name=row[8],
                source_column_name=row[9],
                target_table_name=row[10],
                target_column_name=row[11],
            )
            for row in rows
        ]

    async def delete_relationship(self, rel_id: str) -> bool:
        """Delete a relationship by ID. Returns True if deleted."""
        result = await self.db.execute(
            text("DELETE FROM structured_relationship WHERE id = :id"),
            {"id": rel_id},
        )
        await self.db.flush()
        return result.rowcount > 0
