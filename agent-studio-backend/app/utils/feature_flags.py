"""
Feature flag system for gradual rollout and A/B testing.

Provides a simple, environment-based feature flag system that allows
enabling/disabling features without code changes.
"""

import os
import logging
from typing import Dict, Optional, Set
from enum import Enum

logger = logging.getLogger(__name__)


class FeatureFlag(str, Enum):
    """
    Enumeration of available feature flags.
    
    Add new flags here as needed for gradual rollouts.
    """
    # Knowledge base features
    KB_HYBRID_SEARCH = "kb_hybrid_search"
    KB_RERANKING = "kb_reranking"
    
    # Agent features
    MULTI_AGENT_MODE = "multi_agent_mode"
    RESEARCH_MODE = "research_mode"
    PARALLEL_TOOL_EXECUTION = "parallel_tool_execution"
    
    # Performance optimizations
    CONNECTION_POOLING = "connection_pooling"
    EMBEDDING_CACHE = "embedding_cache"
    QUERY_CACHE = "query_cache"
    
    # Production features
    RATE_LIMITING = "rate_limiting"
    REQUEST_VALIDATION = "request_validation"
    DETAILED_HEALTH_CHECKS = "detailed_health_checks"
    
    # Experimental features
    STREAMING_RESPONSES = "streaming_responses"
    CUSTOM_TOOLS = "custom_tools"
    WORKFLOW_VERSIONING = "workflow_versioning"


class FeatureFlagManager:
    """
    Manages feature flags for the application.
    
    Supports:
    - Environment variable configuration
    - In-memory overrides (for testing)
    - Default values
    - User/session-specific overrides
    """
    
    def __init__(self):
        """Initialize feature flag manager."""
        self._defaults: Dict[str, bool] = {
            # KB features - enabled by default
            FeatureFlag.KB_HYBRID_SEARCH: True,
            FeatureFlag.KB_RERANKING: True,
            
            # Agent features - enabled by default
            FeatureFlag.MULTI_AGENT_MODE: True,
            FeatureFlag.RESEARCH_MODE: True,
            FeatureFlag.PARALLEL_TOOL_EXECUTION: True,
            
            # Performance optimizations - enabled by default
            FeatureFlag.CONNECTION_POOLING: True,
            FeatureFlag.EMBEDDING_CACHE: False,  # Not implemented yet
            FeatureFlag.QUERY_CACHE: False,  # Skipped per user decision
            
            # Production features - enabled by default
            FeatureFlag.RATE_LIMITING: True,
            FeatureFlag.REQUEST_VALIDATION: True,
            FeatureFlag.DETAILED_HEALTH_CHECKS: True,
            
            # Experimental features - disabled by default
            FeatureFlag.STREAMING_RESPONSES: False,
            FeatureFlag.CUSTOM_TOOLS: False,
            FeatureFlag.WORKFLOW_VERSIONING: False,
        }
        
        # In-memory overrides (for testing/dynamic changes)
        self._overrides: Dict[str, bool] = {}
        
        # User-specific overrides (e.g., beta users)
        self._user_overrides: Dict[str, Set[str]] = {}
        
        # Load from environment variables
        self._load_from_env()
    
    def _load_from_env(self):
        """
        Load feature flags from environment variables.
        
        Format: FEATURE_FLAG_{FLAG_NAME}=true/false
        Example: FEATURE_FLAG_KB_RERANKING=false
        """
        for flag in FeatureFlag:
            env_key = f"FEATURE_FLAG_{flag.value.upper()}"
            env_value = os.getenv(env_key)
            
            if env_value is not None:
                enabled = env_value.lower() in ("true", "1", "yes", "on")
                self._defaults[flag.value] = enabled
                logger.debug(
                    "Feature flag '%s' loaded from env: %s",
                    flag.value,
                    "enabled" if enabled else "disabled"
                )
    
    def is_enabled(
        self,
        flag: FeatureFlag,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Check if a feature flag is enabled.
        
        Priority (highest to lowest):
        1. User-specific override
        2. In-memory override
        3. Environment variable
        4. Default value
        
        Args:
            flag: Feature flag to check
            user_id: Optional user ID for user-specific flags
            session_id: Optional session ID for session-specific flags
            
        Returns:
            True if feature is enabled, False otherwise
        """
        flag_name = flag.value if isinstance(flag, FeatureFlag) else flag
        
        # Check user-specific overrides
        if user_id and user_id in self._user_overrides:
            if flag_name in self._user_overrides[user_id]:
                logger.debug("Feature '%s' enabled for user %s", flag_name, user_id)
                return True
        
        # Check in-memory overrides
        if flag_name in self._overrides:
            return self._overrides[flag_name]
        
        # Return default value
        return self._defaults.get(flag_name, False)
    
    def enable(self, flag: FeatureFlag, user_id: Optional[str] = None):
        """
        Enable a feature flag.
        
        Args:
            flag: Feature flag to enable
            user_id: If provided, enable only for this user
        """
        flag_name = flag.value if isinstance(flag, FeatureFlag) else flag
        
        if user_id:
            if user_id not in self._user_overrides:
                self._user_overrides[user_id] = set()
            self._user_overrides[user_id].add(flag_name)
            logger.debug("Enabled feature '%s' for user %s", flag_name, user_id)
        else:
            self._overrides[flag_name] = True
            logger.debug("Enabled feature '%s' globally", flag_name)
    
    def disable(self, flag: FeatureFlag, user_id: Optional[str] = None):
        """
        Disable a feature flag.
        
        Args:
            flag: Feature flag to disable
            user_id: If provided, disable only for this user
        """
        flag_name = flag.value if isinstance(flag, FeatureFlag) else flag
        
        if user_id:
            if user_id in self._user_overrides:
                self._user_overrides[user_id].discard(flag_name)
            logger.debug("Disabled feature '%s' for user %s", flag_name, user_id)
        else:
            self._overrides[flag_name] = False
            logger.debug("Disabled feature '%s' globally", flag_name)
    
    def reset(self, flag: Optional[FeatureFlag] = None):
        """
        Reset feature flag(s) to default values.
        
        Args:
            flag: Specific flag to reset, or None to reset all
        """
        if flag:
            flag_name = flag.value if isinstance(flag, FeatureFlag) else flag
            self._overrides.pop(flag_name, None)
            logger.debug("Reset feature '%s' to default", flag_name)
        else:
            self._overrides.clear()
            self._user_overrides.clear()
            logger.debug("Reset all feature flags to defaults")
    
    def get_all_flags(self) -> Dict[str, bool]:
        """
        Get all feature flags and their current states.
        
        Returns:
            Dictionary of flag name to enabled state
        """
        result = self._defaults.copy()
        result.update(self._overrides)
        return result
    
    def export_config(self) -> Dict[str, any]:
        """
        Export current feature flag configuration.
        
        Useful for debugging and configuration management.
        
        Returns:
            Dictionary with flag states and metadata
        """
        return {
            "flags": self.get_all_flags(),
            "overrides": self._overrides,
            "user_count": len(self._user_overrides),
            "source": "environment + overrides"
        }


# Global feature flag manager instance
_feature_flags: Optional[FeatureFlagManager] = None


def get_feature_flags() -> FeatureFlagManager:
    """
    Get the global feature flag manager instance.
    
    Returns:
        FeatureFlagManager: Singleton instance
    """
    global _feature_flags
    if _feature_flags is None:
        _feature_flags = FeatureFlagManager()
        logger.debug("Initialized feature flag manager")
    return _feature_flags


def is_feature_enabled(
    flag: FeatureFlag,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> bool:
    """
    Convenience function to check if a feature is enabled.
    
    Args:
        flag: Feature flag to check
        user_id: Optional user ID
        session_id: Optional session ID
        
    Returns:
        True if feature is enabled
    """
    return get_feature_flags().is_enabled(flag, user_id, session_id)


# Example usage:
#
# from utils.feature_flags import FeatureFlag, is_feature_enabled
#
# if is_feature_enabled(FeatureFlag.KB_RERANKING):
#     results = await reranker.rerank(query, results)
#
# # Enable for specific user (beta testing)
# from utils.feature_flags import get_feature_flags
# flags = get_feature_flags()
# flags.enable(FeatureFlag.STREAMING_RESPONSES, user_id="beta_user_123")






