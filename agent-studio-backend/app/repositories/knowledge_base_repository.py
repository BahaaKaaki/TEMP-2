"""
Knowledge Base repository for managing KB entities and dynamic chunk tables.
"""
from typing import Optional, List
from sqlalchemy import select, update, and_, text
from sqlalchemy.ext.asyncio import AsyncSession
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

from .base import BaseRepository
from config.settings import settings
from db.models import KnowledgeBaseEntity
from domain.entities.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
    ChunkingConfig,
    EmbeddingModel,
    DocumentChunk,
    MetadataFieldDef,
)


class KnowledgeBaseRepository(BaseRepository[KnowledgeBaseEntity, KnowledgeBase]):
    """Repository for managing knowledge bases."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, KnowledgeBaseEntity)
    
    def _to_domain(self, entity: KnowledgeBaseEntity) -> KnowledgeBase:
        """Convert database entity to domain entity."""
        return KnowledgeBase(
            id=entity.id,
            session_id=entity.sessionId,
            name=entity.name,
            description=entity.description,
            azure_folder_path=entity.azureFolderPath,
            chunk_table_name=entity.chunkTableName,
            chunking_config=ChunkingConfig.from_dict(json.loads(entity.chunkingConfig)),
            embedding_model=EmbeddingModel(entity.embeddingModel),
            vector_dimension=entity.vectorDimension,
            status=KnowledgeBaseStatus(entity.status),
            document_count=entity.documentCount,
            chunk_count=entity.chunkCount,
            total_size_bytes=entity.totalSizeBytes,
            metadata=json.loads(entity.kb_metadata) if entity.kb_metadata else None,
            created_by=entity.createdBy,
            created_at=entity.createdAt,
            updated_at=entity.updatedAt,
            deleted_at=entity.deletedAt,
            metadata_schema=(
                [MetadataFieldDef.from_dict(f) for f in json.loads(entity.metadataSchema)]
                if entity.metadataSchema else None
            ),
            has_structured_data=bool(getattr(entity, 'hasStructuredData', False)),
            is_pinned=bool(getattr(entity, 'isPinned', False)),
            last_accessed_at=getattr(entity, 'lastAccessedAt', None),
            is_public=bool(getattr(entity, 'isPublic', False)),
        )
    
    async def list_all(self, include_deleted: bool = False) -> List[KnowledgeBase]:
        """List all knowledge bases."""
        query = select(KnowledgeBaseEntity)
        if not include_deleted:
            query = query.where(KnowledgeBaseEntity.deletedAt.is_(None))
        
        result = await self.db.execute(query)
        entities = result.scalars().all()
        return [self._to_domain(entity) for entity in entities]
    
    async def create_kb(
        self,
        kb_id: str,
        session_id: str,
        name: str,
        azure_folder_path: str,
        chunk_table_name: str,
        chunking_config: ChunkingConfig,
        embedding_model: EmbeddingModel,
        vector_dimension: int,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        created_by: Optional[str] = None,
        metadata_schema: Optional[list] = None,
    ) -> KnowledgeBase:
        """Create new knowledge base."""
        entity = KnowledgeBaseEntity(
            id=kb_id,
            sessionId=session_id,
            name=name,
            description=description,
            azureFolderPath=azure_folder_path,
            chunkTableName=chunk_table_name,
            chunkingConfig=json.dumps(chunking_config.to_dict()),
            embeddingModel=embedding_model.value,
            vectorDimension=vector_dimension,
            status=KnowledgeBaseStatus.CREATING.value,
            documentCount=0,
            chunkCount=0,
            totalSizeBytes=0,
            kb_metadata=json.dumps(metadata) if metadata else None,
            metadataSchema=json.dumps(metadata_schema) if metadata_schema else None,
            createdBy=created_by,
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow()
        )
        
        await self.create(entity)
        return self._to_domain(entity)
    
    async def get_by_id(self, kb_id: str) -> Optional[KnowledgeBase]:
        """Get KB by ID."""
        entity = await super().get_by_id(kb_id)
        return self._to_domain(entity) if entity else None
    
    async def find_document_id_by_name(self, kb_id: str, file_name: str) -> Optional[str]:
        """Find a document ID by file name (case-insensitive) within a KB."""
        q = text(
            'SELECT id FROM rag_document '
            'WHERE "kbId" = :kb_id AND LOWER("fileName") = LOWER(:file_name) AND "deletedAt" IS NULL '
            'LIMIT 1'
        )
        result = await self.db.execute(q, {"kb_id": kb_id, "file_name": file_name})
        row = result.fetchone()
        return row[0] if row else None

    async def get_by_name(self, session_id: str, name: str) -> Optional[KnowledgeBase]:
        """Get KB by name within a session."""
        query = select(KnowledgeBaseEntity).where(
            and_(
                KnowledgeBaseEntity.sessionId == session_id,
                KnowledgeBaseEntity.name == name,
                KnowledgeBaseEntity.deletedAt.is_(None)
            )
        )
        result = await self.db.execute(query)
        entity = result.scalar_one_or_none()
        return self._to_domain(entity) if entity else None
    
    async def get_by_session_id(
        self,
        session_id: str,
        include_deleted: bool = False
    ) -> List[KnowledgeBase]:
        """Get all KBs for a session."""
        query = select(KnowledgeBaseEntity).where(
            KnowledgeBaseEntity.sessionId == session_id
        )
        
        if not include_deleted:
            query = query.where(KnowledgeBaseEntity.deletedAt.is_(None))
        
        query = query.order_by(KnowledgeBaseEntity.createdAt.desc())
        
        result = await self.db.execute(query)
        entities = result.scalars().all()
        return [self._to_domain(entity) for entity in entities]
    
    async def update_status(
        self,
        kb_id: str,
        status: KnowledgeBaseStatus
    ) -> None:
        """Update KB status."""
        query = (
            update(KnowledgeBaseEntity)
            .where(KnowledgeBaseEntity.id == kb_id)
            .values(status=status.value, updatedAt=datetime.utcnow())
        )
        await self.db.execute(query)
    
    async def increment_counts(
        self,
        kb_id: str,
        document_count: int = 0,
        chunk_count: int = 0,
        size_bytes: int = 0
    ) -> None:
        """Increment KB counters."""
        query = text("""
            UPDATE knowledge_base 
            SET 
                "documentCount" = "documentCount" + :doc_count,
                "chunkCount" = "chunkCount" + :chunk_count,
                "totalSizeBytes" = "totalSizeBytes" + :size_bytes,
                "updatedAt" = :updated_at
            WHERE id = :kb_id
        """)
        
        await self.db.execute(query, {
            "kb_id": kb_id,
            "doc_count": document_count,
            "chunk_count": chunk_count,
            "size_bytes": size_bytes,
            "updated_at": datetime.utcnow()
        })
    
    async def delete_chunks_by_document_id(
        self,
        table_name: str,
        document_id: str
    ) -> int:
        """Delete all chunks for a specific document from the chunk table.

        Returns the number of deleted rows.
        """
        delete_sql = text(f"DELETE FROM {table_name} WHERE document_id = :document_id")
        result = await self.db.execute(delete_sql, {"document_id": document_id})
        return result.rowcount

    async def recalculate_counts(
        self,
        kb_id: str,
        chunk_table_name: str
    ) -> None:
        """Recalculate KB counters from actual data instead of relying on increments."""
        query = text(f"""
            UPDATE knowledge_base
            SET
                "documentCount" = (
                    SELECT COUNT(*) FROM rag_document
                    WHERE "kbId" = :kb_id AND "deletedAt" IS NULL
                ),
                "chunkCount" = (
                    SELECT COUNT(*) FROM {chunk_table_name}
                    WHERE kb_id = :kb_id
                ),
                "totalSizeBytes" = COALESCE(
                    (SELECT SUM("fileSize") FROM rag_document
                     WHERE "kbId" = :kb_id AND "deletedAt" IS NULL),
                    0
                ),
                "updatedAt" = :updated_at
            WHERE id = :kb_id
        """)
        await self.db.execute(query, {
            "kb_id": kb_id,
            "updated_at": datetime.utcnow()
        })

    async def soft_delete(self, kb_id: str) -> None:
        """Soft delete KB."""
        query = (
            update(KnowledgeBaseEntity)
            .where(KnowledgeBaseEntity.id == kb_id)
            .values(
                deletedAt=datetime.utcnow(),
                updatedAt=datetime.utcnow()
            )
        )
        await self.db.execute(query)
    
    async def create_chunk_table(
        self,
        table_name: str,
        vector_dimension: int,
        metadata_fields: Optional[list] = None,
    ) -> None:
        """Create dynamic chunk table for KB.

        Args:
            table_name: SQL-safe table name.
            vector_dimension: Embedding size for the vector column.
            metadata_fields: Optional list of MetadataFieldDef dicts for
                creating typed expression indexes on the JSONB metadata column.
        """
        index_type = settings.VECTOR_INDEX_TYPE.lower()

        if index_type == 'vchordrq':
            create_extension_sql = text("CREATE EXTENSION IF NOT EXISTS vchord CASCADE;")
            await self.db.execute(create_extension_sql)
            logger.debug(f"Using VectorChord (vchordrq) index for table {table_name}")
        elif index_type == 'diskann':
            create_extension_sql = text("CREATE EXTENSION IF NOT EXISTS vector CASCADE;")
            await self.db.execute(create_extension_sql)
            logger.debug(f"Using DiskANN index for table {table_name}")
        else:
            logger.warning(f"Unknown VECTOR_INDEX_TYPE '{index_type}', defaulting to vchordrq")
            create_extension_sql = text("CREATE EXTENSION IF NOT EXISTS vchord CASCADE;")
            await self.db.execute(create_extension_sql)
            index_type = 'vchordrq'

        create_table_sql = text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                kb_id VARCHAR(36) NOT NULL,
                document_id VARCHAR(36) NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                chunk_size INTEGER NOT NULL,
                document_title TEXT,
                chunk_text_tsv tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', COALESCE(document_title, '') || ' ' || chunk_text)
                ) STORED,
                embedding vector({vector_dimension}),
                embedding_status VARCHAR(20) DEFAULT 'pending',
                metadata JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (kb_id) REFERENCES knowledge_base(id) ON DELETE CASCADE,
                FOREIGN KEY (document_id) REFERENCES rag_document(id) ON DELETE CASCADE
            );
        """)

        await self.db.execute(create_table_sql)

        await self.db.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_kb ON {table_name}(kb_id);"))
        await self.db.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_doc ON {table_name}(document_id);"))

        distance_metric = settings.VECTOR_DISTANCE_METRIC.lower()
        ops_type = 'vector_cosine_ops' if distance_metric == 'cosine' else 'vector_l2_ops'

        if index_type == 'vchordrq':
            await self.db.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_embedding ON {table_name} USING vchordrq (embedding {ops_type});"))
            logger.debug(f"Created vchordrq index with {ops_type}")
        elif index_type == 'diskann':
            await self.db.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_embedding ON {table_name} USING diskann (embedding {ops_type});"))
            logger.debug(f"Created diskann index with {ops_type}")

        await self.db.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_tsv ON {table_name} USING GIN (chunk_text_tsv);"))

        # GIN index on the JSONB metadata column for containment queries
        await self.db.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_metadata ON {table_name} USING GIN (metadata jsonb_path_ops);"
        ))

        if metadata_fields:
            for field_def in metadata_fields:
                fname = field_def["name"]
                ftype = field_def["type"]
                safe_name = fname[:48].replace(" ", "_")
                idx_name = f"idx_{table_name}_meta_{safe_name}"
                try:
                    if ftype == "date":
                        await self.db.execute(text(
                            f"CREATE INDEX IF NOT EXISTS {idx_name} "
                            f"ON {table_name} (((metadata->>'{fname}')::date));"
                        ))
                    elif ftype == "number":
                        await self.db.execute(text(
                            f"CREATE INDEX IF NOT EXISTS {idx_name} "
                            f"ON {table_name} (((metadata->>'{fname}')::numeric));"
                        ))
                    logger.debug("Created expression index %s for metadata field '%s'", idx_name, fname)
                except Exception as exc:
                    logger.warning("Could not create expression index for '%s': %s", fname, exc)
    
    async def drop_chunk_table(self, table_name: str) -> None:
        """Drop chunk table for KB."""
        drop_sql = text(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        await self.db.execute(drop_sql)
    
    async def insert_chunk(
        self,
        table_name: str,
        chunk: DocumentChunk
    ) -> None:
        """Insert single chunk into KB's chunk table."""
        insert_sql = text(f"""
            INSERT INTO {table_name} 
                (id, kb_id, document_id, chunk_index, chunk_text, chunk_size, 
                 document_title, embedding, embedding_status, metadata, created_at)
            VALUES 
                (:id, :kb_id, :document_id, :chunk_index, :chunk_text, :chunk_size,
                 :document_title, :embedding, :embedding_status, :metadata, :created_at)
        """)
        
        # Convert embedding list to PostgreSQL vector format
        embedding_str = None
        if chunk.embedding:
            # Format: '[0.1, 0.2, 0.3]' as string for pgvector
            embedding_str = '[' + ','.join(map(str, chunk.embedding)) + ']'
        
        await self.db.execute(insert_sql, {
            "id": chunk.id,
            "kb_id": chunk.kb_id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "chunk_text": chunk.chunk_text,
            "chunk_size": chunk.chunk_size,
            "document_title": chunk.document_title,  # Added for BM25
            "embedding": embedding_str,
            "embedding_status": chunk.embedding_status or 'pending',
            "metadata": json.dumps(chunk.metadata) if chunk.metadata else None,
            "created_at": chunk.created_at
        })
    
    async def bulk_insert_chunks(
        self,
        table_name: str,
        chunks: List[DocumentChunk]
    ) -> None:
        """
        Batch insert multiple chunks in a single query.
        
        This is 95%+ faster than inserting chunks one-by-one for large batches.
        For 100 chunks: 1 query (~50-100ms) vs 100 queries (~2-5 seconds).
        
        Args:
            table_name: Name of the chunk table
            chunks: List of chunks to insert
        """
        if not chunks:
            return
        
        # Build batch insert SQL (CAST metadata text to JSONB for the JSONB column)
        insert_sql = text(f"""
            INSERT INTO {table_name} 
                (id, kb_id, document_id, chunk_index, chunk_text, chunk_size, 
                 document_title, embedding, embedding_status, metadata, created_at)
            VALUES 
                (:id, :kb_id, :document_id, :chunk_index, :chunk_text, :chunk_size,
                 :document_title, :embedding, :embedding_status,
                 CAST(:metadata AS JSONB), :created_at)
        """)
        
        # Prepare batch of parameters
        batch_params = []
        for chunk in chunks:
            # Convert embedding list to PostgreSQL vector format
            embedding_str = None
            if chunk.embedding:
                embedding_str = '[' + ','.join(map(str, chunk.embedding)) + ']'
            
            meta_val = json.dumps(chunk.metadata) if chunk.metadata else None

            batch_params.append({
                "id": chunk.id,
                "kb_id": chunk.kb_id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "chunk_text": chunk.chunk_text,
                "chunk_size": chunk.chunk_size,
                "document_title": chunk.document_title,
                "embedding": embedding_str,
                "embedding_status": chunk.embedding_status or 'pending',
                "metadata": meta_val,
                "created_at": chunk.created_at
            })
        
        # Execute batch insert
        await self.db.execute(insert_sql, batch_params)
    
    async def get_chunks_by_document(
        self,
        table_name: str,
        document_id: str
    ) -> List[DocumentChunk]:
        """Get all chunks for a document."""
        query = text(f"""
            SELECT id, kb_id, document_id, chunk_index, chunk_text, chunk_size,
                   embedding, embedding_status, metadata, created_at
            FROM {table_name}
            WHERE document_id = :document_id
            ORDER BY chunk_index
        """)
        
        result = await self.db.execute(query, {"document_id": document_id})
        rows = result.fetchall()
        
        return [
            DocumentChunk(
                id=row[0],
                kb_id=row[1],
                document_id=row[2],
                chunk_index=row[3],
                chunk_text=row[4],
                chunk_size=row[5],
                embedding=row[6],
                embedding_status=row[7],
                metadata=row[8] if isinstance(row[8], dict) else (json.loads(row[8]) if row[8] else None),
                created_at=row[9]
            )
            for row in rows
        ]
    
    async def get_chunks_paginated(
        self,
        table_name: str,
        document_id: str,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
    ) -> dict:
        """Get paginated chunks with optional keyword search."""
        params: dict = {"document_id": document_id}
        where = "WHERE document_id = :document_id"
        if search:
            where += " AND chunk_text ILIKE :search"
            params["search"] = f"%{search}%"

        count_query = text(f"SELECT COUNT(*) FROM {table_name} {where}")
        count_result = await self.db.execute(count_query, params)
        total = count_result.scalar() or 0

        offset = (page - 1) * page_size
        params["limit"] = page_size
        params["offset"] = offset

        data_query = text(f"""
            SELECT id, kb_id, document_id, chunk_index, chunk_text, chunk_size,
                   embedding_status, created_at
            FROM {table_name}
            {where}
            ORDER BY chunk_index
            LIMIT :limit OFFSET :offset
        """)
        result = await self.db.execute(data_query, params)
        rows = result.fetchall()

        chunks = [
            {
                "chunk_id": row[0],
                "chunk_index": row[1] if row[3] is None else row[3],
                "chunk_text": row[4],
                "chunk_size": row[5],
                "embedding_status": row[6],
                "created_at": row[7].isoformat() if row[7] else None,
            }
            for row in rows
        ]

        import math
        return {
            "chunks": chunks,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if page_size else 1,
        }

    @staticmethod
    def build_metadata_where(
        metadata_filters: Optional[list],
        field_types: Optional[dict] = None,
        table_name: Optional[str] = None,
    ) -> tuple:
        """Build parameterised SQL fragments for metadata JSONB filters.

        Args:
            metadata_filters: List of ``{"field", "operator", "value"}`` dicts.
            field_types: Optional ``{field_name: type_str}`` mapping so the
                correct SQL cast is applied.  When absent the value is treated
                as text.
            table_name: Required when using ``max`` / ``min`` operators so
                the subquery can reference the same table.

        Returns:
            ``(sql_fragment, params)`` where *sql_fragment* is an AND-prefixed
            SQL string (empty string when no filters) and *params* is a dict
            of bind values.
        """
        if not metadata_filters:
            return "", {}

        OPERATOR_MAP = {
            "eq": "=", "neq": "!=",
            "gt": ">", "gte": ">=",
            "lt": "<", "lte": "<=",
            "like": "ILIKE",
        }

        PG_CAST = {
            "date": "date",
            "number": "numeric",
            "boolean": "boolean",
        }

        clauses: list = []
        params: dict = {}
        field_types = field_types or {}

        for idx, filt in enumerate(metadata_filters):
            fname = filt.get("field", "")
            op_key = filt.get("operator", "eq")
            val = filt.get("value")
            ftype = field_types.get(fname, "string")

            if not fname:
                continue

            if op_key in ("max", "min"):
                if not table_name:
                    continue
                agg = "MAX" if op_key == "max" else "MIN"
                pg_type = PG_CAST.get(ftype, "text")
                col_expr = f"CAST(metadata->>'{fname}' AS {pg_type})"
                subq = (
                    f"(SELECT {agg}({col_expr}) FROM {table_name} "
                    f"WHERE kb_id = :kb_id AND metadata->>'{fname}' IS NOT NULL)"
                )
                clauses.append(f"{col_expr} = {subq}")
                continue

            if val is None:
                continue

            sql_op = OPERATOR_MAP.get(op_key)
            if not sql_op:
                continue

            pkey = f"mf_{idx}"

            if op_key == "like":
                clauses.append(f"metadata->>'{fname}' ILIKE :{pkey}")
                params[pkey] = f"%{val}%"
            elif ftype == "date":
                clauses.append(f"CAST(metadata->>'{fname}' AS date) {sql_op} CAST(:{pkey} AS date)")
                params[pkey] = str(val)
            elif ftype == "number":
                clauses.append(f"CAST(metadata->>'{fname}' AS numeric) {sql_op} CAST(:{pkey} AS numeric)")
                params[pkey] = str(val)
            elif ftype == "boolean":
                clauses.append(f"CAST(metadata->>'{fname}' AS boolean) {sql_op} CAST(:{pkey} AS boolean)")
                params[pkey] = str(val).lower()
            else:
                clauses.append(f"metadata->>'{fname}' {sql_op} :{pkey}")
                params[pkey] = str(val)

        if not clauses:
            return "", {}
        sql_fragment = " AND " + " AND ".join(clauses)
        return sql_fragment, params

    async def similarity_search(
        self,
        table_name: str,
        kb_id: str,
        query_embedding: List[float],
        limit: int = 10,
        distance_threshold: Optional[float] = None,
        use_sphere: bool = True,
        metadata_filters: Optional[list] = None,
        metadata_field_types: Optional[dict] = None,
        document_id: Optional[str] = None,
    ) -> List[tuple]:
        """
        Perform similarity search in KB using configured distance metric.
        
        Args:
            table_name: Chunk table name
            kb_id: Knowledge base ID
            query_embedding: Query vector
            limit: Max results
            distance_threshold: Distance threshold
            use_sphere: If True, use sphere search (faster); if False, use ORDER BY
        
        Returns:
            List of tuples with chunk data
        """
        query_embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

        distance_metric = settings.VECTOR_DISTANCE_METRIC.lower()
        distance_op = '<=>' if distance_metric == 'cosine' else '<->'

        meta_sql, meta_params = self.build_metadata_where(
            metadata_filters, metadata_field_types, table_name=table_name,
        )
        doc_filter_sql = ""
        base_params = {"kb_id": kb_id, "limit": limit}
        base_params.update(meta_params)
        if document_id:
            doc_filter_sql = "AND document_id = :doc_filter_id"
            base_params["doc_filter_id"] = document_id

        if use_sphere and distance_threshold:
            search_sql = text(f"""
                SELECT
                    id, document_id, chunk_index, chunk_text, chunk_size,
                    metadata, created_at,
                    (embedding {distance_op} '{query_embedding_str}'::vector) as distance
                FROM {table_name}
                WHERE kb_id = :kb_id
                    AND embedding IS NOT NULL
                    AND embedding <<{distance_op}>> sphere('{query_embedding_str}'::vector, :threshold)
                    {doc_filter_sql}
                    {meta_sql}
                ORDER BY embedding {distance_op} '{query_embedding_str}'::vector
                LIMIT :limit
            """)
            base_params["threshold"] = distance_threshold

            result = await self.db.execute(search_sql, base_params)
        elif distance_threshold:
            search_sql = text(f"""
                SELECT
                    id, document_id, chunk_index, chunk_text, chunk_size,
                    metadata, created_at,
                    (embedding {distance_op} '{query_embedding_str}'::vector) as distance
                FROM {table_name}
                WHERE kb_id = :kb_id
                    AND embedding IS NOT NULL
                    AND (embedding {distance_op} '{query_embedding_str}'::vector) <= :threshold
                    {doc_filter_sql}
                    {meta_sql}
                ORDER BY embedding {distance_op} '{query_embedding_str}'::vector
                LIMIT :limit
            """)
            base_params["threshold"] = distance_threshold

            result = await self.db.execute(search_sql, base_params)
        else:
            search_sql = text(f"""
                SELECT
                    id, document_id, chunk_index, chunk_text, chunk_size,
                    metadata, created_at,
                    (embedding {distance_op} '{query_embedding_str}'::vector) as distance
                FROM {table_name}
                WHERE kb_id = :kb_id
                    AND embedding IS NOT NULL
                    {doc_filter_sql}
                    {meta_sql}
                ORDER BY embedding {distance_op} '{query_embedding_str}'::vector
                LIMIT :limit
            """)

            result = await self.db.execute(search_sql, base_params)

        return result.fetchall()
    
    @staticmethod
    def _build_or_tsquery(query_text: str) -> str:
        """Build an OR-based tsquery string from free-text input.

        Splits the query into individual tokens, strips non-alphanumeric
        characters, and joins with ``|`` (OR) so a chunk matching *any*
        term is returned (ranked by how many terms match).

        Uses the ``simple`` configuration (no stemming) so proper nouns,
        names, and brand terms match exactly.  A parallel ``english``
        stemmed query is OR-ed in so stemmed forms also match.

        Returns a raw tsquery expression string for use in
        ``to_tsquery('simple', ...)``.
        """
        import re
        tokens = re.findall(r"[A-Za-z0-9]+", query_text)
        tokens = [t.lower() for t in tokens if len(t) >= 2]
        if not tokens:
            return ""
        return " | ".join(tokens)

    async def bm25_search(
        self,
        table_name: str,
        kb_id: str,
        query_text: str,
        limit: int = 10,
        metadata_filters: Optional[list] = None,
        metadata_field_types: Optional[dict] = None,
        document_id: Optional[str] = None,
    ) -> List[tuple]:
        """
        Perform BM25 full-text search using PostgreSQL tsvector.

        Uses OR logic: a chunk matching ANY query term is returned,
        ranked by how many terms match and their proximity.
        """
        logger.debug("🔎 BM25 search - table: %s, kb_id: %s, query: '%s', limit: %d",
                   table_name, kb_id, query_text[:100], limit)

        or_expr = self._build_or_tsquery(query_text)
        if not or_expr:
            logger.warning("⚠️  BM25 query produced no usable tokens: '%s'", query_text)
            return []

        meta_sql, meta_params = self.build_metadata_where(
            metadata_filters, metadata_field_types, table_name=table_name,
        )
        doc_filter_sql = ""
        if document_id:
            doc_filter_sql = "AND document_id = :doc_filter_id"

        search_sql = text(f"""
            WITH query_parsed AS (
                SELECT (
                    to_tsquery('simple', :or_expr)
                    || to_tsquery('english', :or_expr)
                ) as query
            )
            SELECT
                id, document_id, chunk_index, chunk_text, chunk_size,
                metadata, created_at,
                ts_rank_cd(chunk_text_tsv, query) as rank
            FROM {table_name}, query_parsed
            WHERE kb_id = :kb_id
                AND chunk_text_tsv @@ query
                {doc_filter_sql}
                {meta_sql}
            ORDER BY rank DESC
            LIMIT :limit
        """)

        params = {"kb_id": kb_id, "or_expr": or_expr, "limit": limit}
        params.update(meta_params)
        if document_id:
            params["doc_filter_id"] = document_id

        try:
            result = await self.db.execute(search_sql, params)

            rows = result.fetchall()
            logger.debug("✅ BM25 search completed - found %d results (query tokens: %s)",
                       len(rows), or_expr[:120])

            if rows:
                logger.debug("   First result rank: %.4f, text preview: %s",
                           rows[0][7], rows[0][3][:100])
            else:
                logger.warning("⚠️  BM25 returned 0 results for query: '%s'", query_text)

            return rows

        except Exception as e:
            logger.error("❌ BM25 search failed: %s", e, exc_info=True)
            return []
    
    async def hybrid_search(
        self,
        table_name: str,
        kb_id: str,
        query_text: str,
        query_embedding: List[float],
        limit: int = 10,
        semantic_weight: float = 0.5,
        rrf_k: int = 60,
        metadata_filters: Optional[list] = None,
        metadata_field_types: Optional[dict] = None,
        document_id: Optional[str] = None,
    ) -> List[tuple]:
        """
        Perform hybrid search using RRF (Reciprocal Rank Fusion).

        Combines semantic (vector) and BM25 (keyword) search.
        Metadata filters are applied to both underlying searches.
        """
        semantic_results = await self.similarity_search(
            table_name=table_name,
            kb_id=kb_id,
            query_embedding=query_embedding,
            limit=limit * 2,
            use_sphere=False,
            metadata_filters=metadata_filters,
            metadata_field_types=metadata_field_types,
            document_id=document_id,
        )

        bm25_results = await self.bm25_search(
            table_name=table_name,
            kb_id=kb_id,
            query_text=query_text,
            limit=limit * 2,
            metadata_filters=metadata_filters,
            metadata_field_types=metadata_field_types,
            document_id=document_id,
        )
        
        # Apply RRF fusion
        rrf_scores = {}
        
        # Add semantic scores (using 1/(k + rank))
        for rank, result in enumerate(semantic_results, 1):
            chunk_id = result[0]
            semantic_score = 1 / (rrf_k + rank)
            rrf_scores[chunk_id] = {
                'result': result,
                'score': semantic_score * semantic_weight
            }
        
        # Add BM25 scores
        for rank, result in enumerate(bm25_results, 1):
            chunk_id = result[0]
            bm25_score = 1 / (rrf_k + rank)
            
            if chunk_id in rrf_scores:
                # Combine scores
                rrf_scores[chunk_id]['score'] += bm25_score * (1 - semantic_weight)
            else:
                # New chunk from BM25
                rrf_scores[chunk_id] = {
                    'result': result,
                    'score': bm25_score * (1 - semantic_weight)
                }
        
        # Sort by combined RRF score and return top k
        sorted_results = sorted(
            rrf_scores.items(),
            key=lambda x: x[1]['score'],
            reverse=True
        )[:limit]
        
        # Return results in same format as similarity_search
        # Format: (id, document_id, chunk_index, chunk_text, chunk_size, metadata, created_at, score)
        return [item[1]['result'] for item in sorted_results]

