"""
Central LLM model registry — single runtime resolver for all binding keys and workflow models.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.model_normalizer import infer_provider, normalize_model_name

logger = logging.getLogger(__name__)

INVENTORY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "llm_models_inventory.yaml"
)

# In-memory cache (populated from DB or YAML fallback)
_models: Dict[str, Dict[str, Any]] = {}
_bindings: Dict[str, Dict[str, Any]] = {}
_cache_loaded = False


@dataclass
class ResolvedModel:
    primary: str
    fallback: Optional[str]
    provider: str
    binding_key: Optional[str] = None


class LlmModelRegistry:
    """Resolve primary/fallback models from the unified catalog."""

    @classmethod
    def get_primary(cls, binding_key: str) -> str:
        cls._ensure_yaml_fallback()
        row = _bindings.get(binding_key)
        if row and row.get("enabled", True):
            return row["primary_model_name"]
        logger.warning("Unknown or disabled binding_key=%s; using env default", binding_key)
        from app.config.llm_config import LLMConfig
        return normalize_model_name(LLMConfig.DEFAULT_MODEL, LLMConfig.DEFAULT_PROVIDER)

    @classmethod
    def get_fallback(
        cls,
        *,
        binding_key: Optional[str] = None,
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Optional[str]:
        cls._ensure_yaml_fallback()
        if binding_key:
            primary = cls.get_primary(binding_key)
            model_row = _models.get(primary, {})
            fb = model_row.get("fallback_model_name")
            if fb:
                return fb
        if model_name:
            normalized = normalize_model_name(model_name, provider)
            model_row = _models.get(normalized, {})
            return model_row.get("fallback_model_name")
        return None

    @classmethod
    def resolve_for_invoke(
        cls,
        *,
        binding_key: Optional[str] = None,
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> ResolvedModel:
        if binding_key:
            primary = cls.get_primary(binding_key)
            fb = cls.get_fallback(binding_key=binding_key)
            return ResolvedModel(
                primary=primary,
                fallback=fb,
                provider=infer_provider(primary),
                binding_key=binding_key,
            )
        primary = normalize_model_name(model_name or "", provider)
        fb = cls.get_fallback(model_name=primary)
        return ResolvedModel(
            primary=primary,
            fallback=fb,
            provider=infer_provider(primary),
        )

    @classmethod
    def _ensure_yaml_fallback(cls) -> None:
        global _cache_loaded
        if _cache_loaded:
            return
        cls.load_from_yaml()

    @classmethod
    def load_from_yaml(cls, path: Optional[Path] = None) -> None:
        global _models, _bindings, _cache_loaded
        path = path or INVENTORY_PATH
        if not path.exists():
            logger.warning("LLM inventory YAML not found at %s", path)
            _cache_loaded = True
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _models = {
            m["model_name"]: m
            for m in data.get("models", [])
            if m.get("model_name")
        }
        _bindings = {
            b["binding_key"]: b
            for b in data.get("bindings", [])
            if b.get("binding_key")
        }
        _cache_loaded = True
        logger.info(
            "Loaded LLM registry from YAML: %d models, %d bindings",
            len(_models),
            len(_bindings),
        )

    @classmethod
    async def refresh_from_db(cls, db: AsyncSession) -> None:
        global _models, _bindings, _cache_loaded
        from app.db.models import LlmModel, LlmModelBinding

        model_rows = (await db.execute(select(LlmModel))).scalars().all()
        binding_rows = (await db.execute(select(LlmModelBinding))).scalars().all()

        if not model_rows and not binding_rows:
            cls.load_from_yaml()
            return

        from app.llm.pricing_for_langfuse import resolve_model_pricing

        _models = {
            r.model_name: {
                "model_name": r.model_name,
                "provider": r.provider,
                "display_label": r.display_label,
                "fallback_model_name": r.fallback_model_name,
                "is_deprecated": r.is_deprecated,
                "pricing": resolve_model_pricing(r),
            }
            for r in model_rows
        }
        _bindings = {
            r.binding_key: {
                "binding_key": r.binding_key,
                "binding_type": r.binding_type,
                "primary_model_name": r.primary_model_name,
                "display_name": r.display_name,
                "enabled": r.enabled,
            }
            for r in binding_rows
        }
        _cache_loaded = True
        logger.info(
            "Refreshed LLM registry from DB: %d models, %d bindings",
            len(_models),
            len(_bindings),
        )

    @classmethod
    def get_model_pricing(cls, model_name: str) -> Optional[Dict[str, Optional[float]]]:
        """USD per 1M tokens from in-memory catalog (populated by refresh_from_db)."""
        cls._ensure_yaml_fallback()
        row = _models.get(model_name) or _models.get(normalize_model_name(model_name))
        if not row:
            return None
        pricing = row.get("pricing")
        if not pricing:
            return None
        if not any(v is not None for v in pricing.values()):
            return None
        return pricing

    @classmethod
    def invalidate_cache(cls) -> None:
        global _cache_loaded, _models, _bindings
        _cache_loaded = False
        _models = {}
        _bindings = {}

    @classmethod
    async def sync_binding_from_db(
        cls, db: AsyncSession, binding_key: str
    ) -> Optional[str]:
        """Refresh one binding from DB into the in-memory registry."""
        from app.db.models import LlmModelBinding

        row = await db.get(LlmModelBinding, binding_key)
        if not row:
            return None
        global _bindings, _cache_loaded
        _bindings[binding_key] = {
            "binding_key": row.binding_key,
            "binding_type": row.binding_type,
            "primary_model_name": row.primary_model_name,
            "display_name": row.display_name,
            "enabled": row.enabled,
        }
        _cache_loaded = True
        if not row.enabled:
            logger.warning("Binding %s is disabled; using env default", binding_key)
            from app.config.llm_config import LLMConfig
            return normalize_model_name(LLMConfig.DEFAULT_MODEL, LLMConfig.DEFAULT_PROVIDER)
        return row.primary_model_name

    @classmethod
    async def ensure_binding_primary(cls, binding_key: str) -> str:
        """Resolve primary model for a binding, syncing that row from DB first."""
        try:
            from db.pgsql import PrimarySessionLocal

            async with PrimarySessionLocal() as db:
                synced = await cls.sync_binding_from_db(db, binding_key)
                if synced:
                    return synced
        except Exception as exc:
            logger.warning(
                "Failed to sync binding %s from DB; using in-memory registry: %s",
                binding_key,
                exc,
            )
        return cls.get_primary(binding_key)

    @classmethod
    async def _catalog_row_counts(cls, db: AsyncSession) -> tuple[int, int]:
        from app.db.models import LlmModel, LlmModelBinding

        model_count = await db.scalar(select(func.count()).select_from(LlmModel)) or 0
        binding_count = await db.scalar(select(func.count()).select_from(LlmModelBinding)) or 0
        return int(model_count), int(binding_count)

    @classmethod
    async def ensure_catalog_loaded(cls, db: AsyncSession, path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Load registry from DB and insert any missing catalog rows from inventory YAML.

        Existing rows (by model_name / binding_key) are never updated — safe on every deploy.
        """
        path = path or INVENTORY_PATH

        if path.exists():
            sync = await cls.seed_from_yaml(db, path=path)
        else:
            logger.warning("LLM inventory YAML missing at %s", path)
            sync = {
                "models_inserted": 0,
                "models_skipped": 0,
                "bindings_inserted": 0,
                "bindings_skipped": 0,
                "yaml_missing": True,
            }

        model_count, binding_count = await cls._catalog_row_counts(db)
        if model_count > 0 or binding_count > 0:
            await cls.refresh_from_db(db)
            return {
                "source": "database",
                "models": model_count,
                "bindings": binding_count,
                **sync,
            }

        cls.load_from_yaml()
        return {
            "source": "yaml_cache_only",
            "models": len(_models),
            "bindings": len(_bindings),
            **sync,
        }

    @classmethod
    async def seed_from_yaml(cls, db: AsyncSession, path: Optional[Path] = None) -> Dict[str, int]:
        """
        Insert missing inventory YAML rows into PostgreSQL (insert-only).

        - llm_models: keyed by model_name — skip if row exists
        - llm_model_bindings: keyed by binding_key — skip if row exists
        - fallback_model_name from YAML is applied only when the model row is newly inserted

        Does not overwrite admin or runtime changes to existing rows.
        """
        from app.db.models import LlmModel, LlmModelBinding

        path = path or INVENTORY_PATH
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        models = data.get("models", [])
        bindings = data.get("bindings", [])

        all_names: set[str] = set()
        for m in models:
            all_names.add(m["model_name"])
            fb = m.get("fallback_model_name")
            if fb:
                all_names.add(fb)
        for b in bindings:
            all_names.add(b["primary_model_name"])

        model_meta = {m["model_name"]: m for m in models}
        models_inserted = 0
        models_skipped = 0
        bindings_inserted = 0
        bindings_skipped = 0
        newly_inserted_models: set[str] = set()

        # Pass 1: insert missing models (no fallback yet — avoids FK ordering issues).
        for name in sorted(all_names):
            if await db.get(LlmModel, name):
                models_skipped += 1
                continue
            meta = model_meta.get(name, {})
            db.add(
                LlmModel(
                    model_name=name,
                    provider=meta.get("provider") or infer_provider(name),
                    display_label=meta.get("display_label") or name,
                    fallback_model_name=None,
                    is_deprecated=bool(meta.get("is_deprecated", False)),
                    discovered_in_proxy=False,
                    updatedAt=datetime.utcnow(),
                )
            )
            newly_inserted_models.add(name)
            models_inserted += 1

        await db.flush()

        # Pass 2: YAML fallbacks only for models inserted in this run.
        for m in models:
            fb = m.get("fallback_model_name")
            if not fb:
                continue
            model_name = m["model_name"]
            if model_name not in newly_inserted_models:
                continue
            row = await db.get(LlmModel, model_name)
            if row:
                row.fallback_model_name = fb
                row.updatedAt = datetime.utcnow()

        # Pass 3: insert missing bindings by binding_key.
        for b in bindings:
            binding_key = b["binding_key"]
            if await db.get(LlmModelBinding, binding_key):
                bindings_skipped += 1
                continue
            db.add(
                LlmModelBinding(
                    binding_key=binding_key,
                    binding_type=b["binding_type"],
                    primary_model_name=b["primary_model_name"],
                    display_name=b.get("display_name"),
                    description=b.get("description"),
                    source_file=b.get("source_file"),
                    enabled=bool(b.get("enabled", True)),
                    updatedAt=datetime.utcnow(),
                )
            )
            bindings_inserted += 1

        await db.commit()
        await cls.refresh_from_db(db)
        logger.info(
            "LLM catalog YAML sync (insert-only): +%d models, +%d bindings "
            "(%d models skipped, %d bindings skipped)",
            models_inserted,
            bindings_inserted,
            models_skipped,
            bindings_skipped,
        )
        return {
            "models_inserted": models_inserted,
            "models_skipped": models_skipped,
            "bindings_inserted": bindings_inserted,
            "bindings_skipped": bindings_skipped,
            "yaml_models": len(all_names),
            "yaml_bindings": len(bindings),
        }

    @classmethod
    async def ensure_model_in_catalog(
        cls,
        db: AsyncSession,
        model_name: str,
        provider: Optional[str] = None,
    ) -> str:
        """Insert model into catalog if missing (workflow scanner)."""
        from app.db.models import LlmModel

        normalized = normalize_model_name(model_name, provider)

        row = await db.get(LlmModel, normalized)
        if not row:
            row = LlmModel(
                model_name=normalized,
                provider=provider or infer_provider(normalized),
                display_label=normalized,
            )
            db.add(row)
            await db.flush()

        _models[normalized] = {
            "model_name": normalized,
            "provider": row.provider,
            "fallback_model_name": row.fallback_model_name,
            "is_deprecated": row.is_deprecated,
        }
        return normalized
