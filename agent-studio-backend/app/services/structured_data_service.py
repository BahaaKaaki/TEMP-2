"""
Structured data service for CSV/Excel uploads in the knowledge base system.

Orchestrates schema preview, confirmation, loading, and semantic model generation.
"""
import asyncio
import logging
import re
import uuid
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from services.base import BaseService
from repositories.structured_data_repository import StructuredDataRepository
from domain.entities.structured_data import (
    StructuredTable,
    StructuredColumn,
    StructuredTableStatus,
    ColumnDataType,
)
from utils.schema_inference import (
    infer_column_types,
    suggest_descriptions,
    parse_csv_data,
    parse_excel_data,
)

logger = logging.getLogger(__name__)


def _sanitize_table_name(name: str) -> str:
    """Remove extension, lowercase, replace non-alphanumeric with underscore, collapse, truncate to 63 chars.
    Prefix with 't_' if it starts with a digit."""
    if not name:
        return ""
    # Remove extension
    base = re.sub(r"\.[^.]+$", "", name)
    # Lowercase, replace non-alphanumeric with underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", base).lower()
    # Collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    # Truncate to 63 chars
    sanitized = sanitized[:63]
    # Prefix with t_ if starts with digit
    if sanitized and sanitized[0].isdigit():
        sanitized = "t_" + sanitized
    return sanitized


class StructuredDataService(BaseService):
    """Service for orchestrating structured data operations (CSV/Excel) in knowledge bases."""

    def __init__(self, db: AsyncSession, structured_repo: StructuredDataRepository):
        super().__init__(db)
        self.structured_repo = structured_repo

    _PG_NAME_LIMIT = 63

    def _sanitize_table_name(self, name: str) -> str:
        """Sanitize table name for PostgreSQL."""
        return _sanitize_table_name(name)

    def _make_table_name(self, file_name: str, sheet_name: Optional[str]) -> str:
        """Build a PG table name that fits within 63 chars.

        For single-sheet files (CSV): use the file name.
        For multi-sheet files (Excel): use a short file prefix + sheet name
        so that the file context is preserved for disambiguation while the
        sheet name keeps its full resolution.
        """
        if not sheet_name:
            return self._sanitize_table_name(
                re.sub(r"\.[^.]+$", "", file_name or "")
            )

        sanitized_sheet = _sanitize_table_name(sheet_name)
        file_base = _sanitize_table_name(
            re.sub(r"\.[^.]+$", "", file_name or "")
        )

        if not file_base:
            return sanitized_sheet

        # Reserve enough space for the sheet name + underscore separator.
        # Use whatever file prefix fits in the remaining budget.
        available_for_prefix = self._PG_NAME_LIMIT - len(sanitized_sheet) - 1
        if available_for_prefix >= 6:
            prefix = file_base[:available_for_prefix]
            return _sanitize_table_name(f"{prefix}_{sanitized_sheet}")

        # Sheet name alone already near the limit — skip the prefix.
        return sanitized_sheet

    # Max concurrent LLM calls for schema description generation.
    _SCHEMA_PREVIEW_CONCURRENCY = 10

    async def preview_schema(
        self, file_content: bytes, file_name: str
    ) -> dict:
        """
        Preview schema for CSV or Excel file.
        Detects file type, parses data, infers column types, suggests descriptions.
        Sheet previews are built concurrently (bounded by _SCHEMA_PREVIEW_CONCURRENCY).
        """
        try:
            ext = (file_name or "").lower().split(".")[-1] if "." in (file_name or "") else ""

            if ext in ("xlsx", "xls"):
                sheets_data = await asyncio.to_thread(parse_excel_data, file_content, file_name)
                tables = await self._build_previews_concurrent(sheets_data, file_name)
            else:
                csv_data = await asyncio.to_thread(parse_csv_data, file_content, file_name)
                table_info = await self._build_table_preview(
                    csv_data, file_name, None
                )
                tables = [table_info] if table_info else []

            return {"is_structured": True, "tables": tables}
        except Exception as e:
            logger.exception("preview_schema failed for %s: %s", file_name, e)
            raise

    async def _build_previews_concurrent(
        self, sheets_data: List[dict], file_name: str
    ) -> List[dict]:
        """Build table previews for multiple sheets concurrently."""
        sem = asyncio.Semaphore(self._SCHEMA_PREVIEW_CONCURRENCY)

        async def _guarded(sheet_data: dict) -> Optional[dict]:
            async with sem:
                try:
                    return await self._build_table_preview(
                        sheet_data, file_name, sheet_data.get("sheet_name")
                    )
                except Exception:
                    logger.warning(
                        "Schema preview failed for sheet '%s' in %s",
                        sheet_data.get("sheet_name", "?"), file_name,
                        exc_info=True,
                    )
                    return None

        results = await asyncio.gather(*[_guarded(sd) for sd in sheets_data])
        return [r for r in results if r is not None]

    async def _build_table_preview(
        self,
        parsed: dict,
        file_name: str,
        sheet_name: Optional[str],
    ) -> Optional[dict]:
        """Build a single table preview from parsed data."""
        headers = parsed.get("headers", [])
        sample_rows = parsed.get("sample_rows", [])
        total_rows = parsed.get("total_rows", 0)

        if not headers:
            return None

        type_results = await asyncio.to_thread(infer_column_types, headers, sample_rows)

        # Suggest descriptions (async)
        desc_result = await suggest_descriptions(
            headers, sample_rows, file_name
        )
        table_description = desc_result.get("table_description", "") or ""
        column_descriptions = desc_result.get("column_descriptions", {}) or {}

        # Build columns list
        columns = []
        for i, tr in enumerate(type_results):
            col_name = tr.get("column_name", headers[i] if i < len(headers) else "")
            display_name = col_name.replace("_", " ").title()
            data_type = tr.get("data_type", "text")
            nullable = tr.get("nullable", True)
            description = column_descriptions.get(col_name, "") or ""

            columns.append({
                "column_name": col_name,
                "display_name": display_name,
                "data_type": data_type,
                "nullable": nullable,
                "description": description,
            })

        table_name = self._make_table_name(file_name, sheet_name)

        return {
            "file_name": file_name,
            "sheet_name": sheet_name,
            "table_name": table_name,
            "headers": headers,
            "sample_rows": sample_rows,
            "total_rows": total_rows,
            "columns": columns,
            "table_description": table_description,
        }

    async def confirm_and_load(
        self,
        kb_id: str,
        document_id: str,
        file_content: bytes,
        file_name: str,
        confirmed_tables: List[dict],
        created_by: Optional[str] = None,
    ) -> List[StructuredTable]:
        """
        Create PG schema, tables, insert rows, and save metadata for confirmed tables.
        """
        try:
            schema_name = f"kb_data_{kb_id[:8]}"
            ext = (file_name or "").lower().split(".")[-1] if "." in (file_name or "") else ""

            existing_names = await self.structured_repo.get_table_names_for_kb(kb_id)
            for ct in confirmed_tables:
                tname = self._sanitize_table_name(ct.get("table_name", "table")).lower()
                if tname in existing_names:
                    raise ValueError(
                        f"Table '{tname}' already exists in this knowledge base. "
                        "Please choose a different name."
                    )

            await self.structured_repo.create_schema(schema_name)

            if ext in ("xlsx", "xls"):
                parsed_sheets = await asyncio.to_thread(parse_excel_data, file_content, file_name)
                parsed_by_sheet: Dict[Optional[str], dict] = {
                    p.get("sheet_name"): p for p in parsed_sheets
                }
            else:
                csv_data = await asyncio.to_thread(parse_csv_data, file_content, file_name)
                parsed_by_sheet = {None: csv_data}

            result_tables: List[StructuredTable] = []
            all_warnings: List[str] = []

            for confirmed in confirmed_tables:
                sheet_name = confirmed.get("sheet_name")
                parsed = parsed_by_sheet.get(sheet_name)
                if not parsed:
                    logger.warning(
                        "No parsed data for sheet %s in %s", sheet_name, file_name
                    )
                    continue

                table_id = str(uuid.uuid4())
                table_name = self._sanitize_table_name(
                    confirmed.get("table_name", "table")
                )

                # Build StructuredColumn domain objects
                columns: List[StructuredColumn] = []
                for idx, col_def in enumerate(confirmed.get("columns", [])):
                    col_id = str(uuid.uuid4())
                    data_type = col_def.get("data_type", "text")
                    if isinstance(data_type, str):
                        try:
                            data_type = ColumnDataType(data_type)
                        except ValueError:
                            data_type = ColumnDataType.TEXT

                    columns.append(
                        StructuredColumn(
                            id=col_id,
                            table_id=table_id,
                            column_name=col_def.get("column_name", ""),
                            display_name=col_def.get("display_name", col_def.get("column_name", "")),
                            data_type=data_type,
                            description=col_def.get("description"),
                            column_order=idx,
                            nullable=col_def.get("nullable", True),
                        )
                    )

                # Create PG table
                await self.structured_repo.create_data_table(
                    schema_name, table_name, columns
                )

                # Build rows in column order
                headers = [c.column_name for c in columns]
                column_types = {c.column_name: c.data_type.value for c in columns}
                orig_headers = parsed.get("headers", [])
                orig_rows = parsed.get("rows", [])

                header_to_idx = {h: i for i, h in enumerate(orig_headers)}
                rows: List[List[str]] = []
                for row in orig_rows:
                    new_row = []
                    for col in columns:
                        idx = header_to_idx.get(col.column_name, -1)
                        val = row[idx] if 0 <= idx < len(row) else ""
                        new_row.append("" if val is None else str(val))
                    rows.append(new_row)

                # Validate a sample before inserting
                data_warnings = self.structured_repo.validate_data_sample(
                    headers, rows, column_types
                )
                for w in data_warnings:
                    logger.warning("Data validation for %s: %s", table_name, w)
                    all_warnings.append(f"[{table_name}] {w}")

                # Insert rows
                await self.structured_repo.insert_rows(
                    schema_name, table_name, headers, rows, column_types
                )

                # Save metadata
                structured_table = StructuredTable(
                    id=table_id,
                    kb_id=kb_id,
                    document_id=document_id,
                    schema_name=schema_name,
                    table_name=table_name,
                    display_name=confirmed.get("display_name", table_name),
                    description=confirmed.get("description"),
                    row_count=len(rows),
                    source_sheet=sheet_name,
                    status=StructuredTableStatus.ACTIVE,
                    created_by=created_by,
                    columns=columns,
                )
                await self.structured_repo.save_table_metadata(structured_table)
                await self.structured_repo.save_column_metadata(columns)

                await self.structured_repo.update_table_status(
                    table_id, StructuredTableStatus.ACTIVE, len(rows)
                )

                result_tables.append(structured_table)

            # Update KB hasStructuredData flag
            await self.structured_repo.update_kb_structured_flag(kb_id, True)

            return result_tables, all_warnings

        except ValueError as e:
            logger.warning("confirm_and_load validation error: %s", e)
            await self.rollback()
            raise
        except Exception as e:
            await self.rollback()
            err_msg = str(e)
            err_lower = err_msg.lower()

            if "notnullviolation" in err_lower or "not-null" in err_lower or "violates not-null constraint" in err_lower:
                col_match = None
                if 'column "' in err_lower:
                    start = err_lower.index('column "') + 8
                    end = err_lower.index('"', start)
                    col_match = err_msg[start:end]
                friendly = (
                    f"Data loading failed: some rows have NULL/empty values in "
                    f"{'column "' + col_match + '"' if col_match else 'a required column'} "
                    f"which the database rejected. This usually means the source data "
                    f"has missing values. The column has been updated to allow NULLs — "
                    f"please try again."
                )
                logger.error("confirm_and_load NOT NULL violation: %s", err_msg)
                raise ValueError(friendly) from e

            if "too many" in err_lower or ("bind" in err_lower and "exceed" in err_lower):
                friendly = (
                    f"The dataset is too large to insert "
                    f"({len(confirmed_tables)} table(s), file: {file_name}). "
                    f"Please try splitting the file into smaller sheets."
                )
                logger.error("confirm_and_load param overflow: %s", err_msg)
                raise ValueError(friendly) from e

            if "integrityerror" in err_lower or "dataerror" in err_lower:
                logger.error("confirm_and_load data error: %s", err_msg)
                detail = err_msg[:300] if len(err_msg) > 300 else err_msg
                raise ValueError(
                    f"Data loading failed due to a data integrity issue: {detail}"
                ) from e

            logger.exception(
                "confirm_and_load failed for kb_id=%s doc_id=%s: %s",
                kb_id, document_id, e,
            )
            raise

    _SAMPLE_ROWS_PER_TABLE = 3

    async def get_semantic_model(self, kb_id: str) -> str:
        """Build a text description of the KB's structured schema for LLM context.

        Column names are sanitized to match the actual PostgreSQL identifiers
        (lowercase, underscores) so the SQL generation LLM produces valid queries.
        Includes sample rows per table so the LLM can see actual data values.
        """
        from app.repositories.structured_data_repository import _sanitize_name
        try:
            tables = await self.structured_repo.get_tables_for_kb(kb_id)
            if not tables:
                return ""

            lines = ["Database Schema for Knowledge Base:\n"]
            for t in tables:
                desc = t.description or ""
                lines.append(f"Table: {t.table_name} - {desc}")
                lines.append("Columns:")
                col_names: List[str] = []
                for c in t.columns:
                    pg_col = _sanitize_name(c.column_name)
                    col_names.append(pg_col)
                    dt = c.data_type.value if isinstance(c.data_type, ColumnDataType) else c.data_type
                    col_desc = c.description or ""
                    lines.append(f"  - {pg_col} ({dt}): {col_desc}")

                sample_lines = await self._fetch_sample_rows(
                    t.schema_name, t.table_name, col_names
                )
                if sample_lines:
                    lines.append("Sample data:")
                    lines.extend(sample_lines)

                lines.append("")

            rels = await self.structured_repo.get_relationships_for_kb(kb_id)
            if rels:
                lines.append("Relationships (for JOINs):")
                for r in rels:
                    src_col = _sanitize_name(r.source_column_name) if r.source_column_name else r.source_column_id
                    tgt_col = _sanitize_name(r.target_column_name) if r.target_column_name else r.target_column_id
                    rel_type = r.relationship_type.value if hasattr(r.relationship_type, 'value') else r.relationship_type
                    lines.append(f"  - {r.source_table_name}.{src_col} -> {r.target_table_name}.{tgt_col} ({rel_type})")
                lines.append("")

            return "\n".join(lines).strip()
        except Exception as e:
            logger.exception("get_semantic_model failed for kb_id=%s: %s", kb_id, e)
            raise

    async def _fetch_sample_rows(
        self,
        schema_name: str,
        table_name: str,
        col_names: List[str],
    ) -> List[str]:
        """Fetch a few sample rows and format them for the semantic model."""
        try:
            preview = await self.structured_repo.get_table_preview(
                schema_name, table_name, page=1, page_size=self._SAMPLE_ROWS_PER_TABLE,
            )
            rows = preview.get("rows", [])
            if not rows:
                return []
            result: List[str] = []
            header = " | ".join(str(c) for c in col_names)
            result.append(f"  {header}")
            for row in rows:
                vals = " | ".join(
                    str(v) if v is not None else "NULL"
                    for v in row[:len(col_names)]
                )
                result.append(f"  {vals}")
            return result
        except Exception as exc:
            logger.debug("Could not fetch sample rows for %s.%s: %s", schema_name, table_name, exc)
            return []

    async def get_tables_for_kb(self, kb_id: str) -> List[StructuredTable]:
        """Get all structured tables for a KB."""
        return await self.structured_repo.get_tables_for_kb(kb_id)

    async def get_table_preview(
        self,
        document_id: str,
        page: int = 1,
        page_size: int = 50,
        sheet_table_id: Optional[str] = None,
    ) -> dict:
        """Get preview data for structured tables (metadata + paginated rows).
        Returns all tables for the document so the frontend can render tabs."""
        try:
            all_tables = await self.structured_repo.get_all_tables_for_document(document_id)
            if not all_tables:
                return {
                    "tables": [],
                    "table": None,
                    "rows": [],
                    "total_rows": 0,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": 0,
                }

            if sheet_table_id:
                active = next((t for t in all_tables if t.id == sheet_table_id), all_tables[0])
            else:
                active = all_tables[0]

            preview = await self.structured_repo.get_table_preview(
                active.schema_name,
                active.table_name,
                page=page,
                page_size=page_size,
            )

            return {
                "tables": [t.to_dict() for t in all_tables],
                "table": active.to_dict(),
                "rows": preview.get("rows", []),
                "total_rows": preview.get("total_rows", 0),
                "page": preview.get("page", page),
                "page_size": preview.get("page_size", page_size),
                "total_pages": preview.get("total_pages", 0),
            }
        except Exception as e:
            logger.exception(
                "get_table_preview failed for document_id=%s: %s",
                document_id, e,
            )
            raise
