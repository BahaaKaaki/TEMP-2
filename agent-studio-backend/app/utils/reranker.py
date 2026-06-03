"""
Reranking utility for improving RAG search results.

Uses cross-encoder models to re-score search results based on query relevance.
"""

import logging
from typing import List, Tuple, Optional
import os
import numpy as np
from app.config.settings import settings

logger = logging.getLogger(__name__)


class Reranker:
    """
    Rerank search results using cross-encoder models.
    
    Cross-encoders score query-document pairs directly,
    providing better relevance than bi-encoder similarity.
    """
    
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Initialize reranker with specified model.
        
        Args:
            model_name: HuggingFace model name for cross-encoder
        """
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.model.eval()  # Set to evaluation mode
            logger.debug(f"✅ Initialized reranker model: {model_name}")
        except ImportError:
            logger.warning(
                "⚠️ transformers not installed! "
                "Run: pip install transformers"
            )
        except Exception as e:
            logger.error(f"❌ Failed to load reranker model {model_name}: {e}")
    
    async def rerank(
        self,
        query: str,
        results: List[tuple],
        top_k: Optional[int] = None
    ) -> List[tuple]:
        """
        Rerank search results based on query relevance.
        
        Args:
            query: User's search query
            results: List of search results (tuples with chunk_text at index 3)
            top_k: Number of top results to return (None = return all, reranked)
        
        Returns:
            Reranked results (same format as input)
        """
        if not self.model or not self.tokenizer:
            logger.warning("Reranker model not available, returning original results")
            return results[:top_k] if top_k else results
        
        if not results:
            return []
        
        try:
            import asyncio
            
            # Extract chunk texts from results
            # Result format: (id, document_id, chunk_index, chunk_text, chunk_size, metadata, created_at, distance/rank)
            texts = [result[3] for result in results]  # chunk_text is at index 3
            
            # Create query-text pairs for cross-encoder
            pairs = [[query, text] for text in texts]
            
            # Run CPU-intensive prediction in thread pool to avoid blocking event loop
            scores = await asyncio.to_thread(
                self._predict_scores,
                pairs
            )
            
            # Combine results with scores
            scored_results = list(zip(results, scores))
            
            # Sort by score (descending)
            scored_results.sort(key=lambda x: x[1], reverse=True)
            
            # Return top_k results (or all if top_k is None)
            if top_k:
                scored_results = scored_results[:top_k]
            
            # Replace distance/rank (index 7) with reranker score
            reranked = []
            for result, score in scored_results:
                result_list = list(result)
                result_list[7] = float(score)  # Replace distance/rank with reranker score
                reranked.append(tuple(result_list))
            
            logger.debug(f"✅ Reranked {len(results)} results, returning top {len(reranked)}")
            return reranked
            
        except Exception as e:
            logger.error(f"❌ Reranking failed: {e}", exc_info=True)
            return results[:top_k] if top_k else results
    
    def _predict_scores(self, pairs: List[List[str]]) -> List[float]:
        """
        Predict relevance scores for query-text pairs using transformers.
        
        Args:
            pairs: List of [query, text] pairs
        
        Returns:
            List of relevance scores
        """
        # Tokenize all pairs at once
        inputs = self.tokenizer(
            pairs,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512
        )
        
        # Get model predictions (no gradient computation needed)
        import torch
        with torch.no_grad():
            outputs = self.model(**inputs)
            # For cross-encoder models, the logit is the relevance score
            scores = outputs.logits.squeeze(-1).cpu().numpy()
        
        # Convert to list
        if scores.ndim == 0:
            scores = [float(scores)]
        else:
            scores = scores.tolist()
        
        return scores
    
    @staticmethod
    def is_available() -> bool:
        """Check if reranking dependencies are available."""
        try:
            import transformers
            return True
        except ImportError:
            return False


# Global reranker instances (lazy loaded)
_reranker_cache = {}


def get_reranker(model_name: Optional[str] = None) -> Reranker:
    """
    Get or create a reranker instance (cached).
    
    Args:
        model_name: HuggingFace cross-encoder model name (defaults to settings.KB_RERANKER_MODEL)
    
    Returns:
        Reranker instance
    """
    # Use default from settings if not specified
    if model_name is None:
        model_name = settings.KB_RERANKER_MODEL
    
    if model_name not in _reranker_cache:
        _reranker_cache[model_name] = Reranker(model_name)
    
    return _reranker_cache[model_name]

