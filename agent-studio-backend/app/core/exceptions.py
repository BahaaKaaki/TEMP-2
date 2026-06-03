"""
Domain exceptions for the application.
"""


class DomainException(Exception):
    """Base exception for domain-level errors."""
    pass


class NotFoundException(DomainException):
    """Base exception for not found errors."""
    pass


class SessionNotFoundException(NotFoundException):
    """Raised when a session is not found."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session {session_id} not found")


class SessionNotActiveException(DomainException):
    """Raised when trying to interact with an inactive session."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session {session_id} is not active")


class WorkflowNotActiveException(DomainException):
    """Raised when trying to execute an inactive workflow."""
    
    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        super().__init__(f"Workflow {workflow_id} is not active")


class WorkflowNotFoundException(NotFoundException):
    """Raised when a workflow is not found."""
    
    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        super().__init__(f"Workflow {workflow_id} not found")


class ExecutionNotFoundException(NotFoundException):
    """Raised when an execution is not found."""
    
    def __init__(self, execution_id: int):
        self.execution_id = execution_id
        super().__init__(f"Execution {execution_id} not found")


class KnowledgeBaseNotFoundException(NotFoundException):
    """Raised when a knowledge base is not found."""
    
    def __init__(self, kb_id: str):
        self.kb_id = kb_id
        super().__init__(f"Knowledge base {kb_id} not found")


class DocumentNotFoundException(NotFoundException):
    """Raised when a document is not found."""
    
    def __init__(self, document_id: str):
        self.document_id = document_id
        super().__init__(f"Document {document_id} not found")


class FileNotFoundException(NotFoundException):
    """Raised when a file is not found."""
    
    def __init__(self, file_id: str):
        self.file_id = file_id
        super().__init__(f"File {file_id} not found")


class DeliverableNotFoundException(NotFoundException):
    """Raised when a deliverable is not found."""
    
    def __init__(self, deliverable_id: str):
        self.deliverable_id = deliverable_id
        super().__init__(f"Deliverable {deliverable_id} not found")


class DeliverableNotPendingException(DomainException):
    """Raised when trying to complete a deliverable that is not pending."""
    
    def __init__(self, deliverable_id: str, current_status: str):
        self.deliverable_id = deliverable_id
        self.current_status = current_status
        super().__init__(f"Deliverable {deliverable_id} is not pending (current status: {current_status})")


class InvalidExecutionStateException(DomainException):
    """Raised when trying to perform an operation on an execution in an invalid state."""
    
    def __init__(self, execution_id: int, current_state: str, required_state: str):
        self.execution_id = execution_id
        self.current_state = current_state
        self.required_state = required_state
        super().__init__(f"Execution {execution_id} is in state {current_state}, but {required_state} is required")


# External API exceptions

class ExternalAPIException(Exception):
    """Base exception for external API errors."""
    pass


class LLMAPIException(ExternalAPIException):
    """Raised when LLM API call fails."""
    
    def __init__(self, provider: str, error: str):
        self.provider = provider
        super().__init__(f"{provider} API error: {error}")


class OpenAIException(LLMAPIException):
    """Raised when OpenAI API call fails."""
    
    def __init__(self, error: str):
        super().__init__("OpenAI", error)


class AnthropicException(LLMAPIException):
    """Raised when Anthropic API call fails."""
    
    def __init__(self, error: str):
        super().__init__("Anthropic", error)


class AzureAPIException(LLMAPIException):
    """Raised when Azure API call fails."""
    
    def __init__(self, error: str):
        super().__init__("Azure", error)


class EmbeddingAPIException(ExternalAPIException):
    """Raised when embedding API call fails."""
    
    def __init__(self, error: str):
        super().__init__(f"Embedding API error: {error}")


class StorageException(ExternalAPIException):
    """Raised when storage operation fails."""
    
    def __init__(self, operation: str, error: str):
        self.operation = operation
        super().__init__(f"Storage {operation} failed: {error}")


class AzureStorageException(StorageException):
    """Raised when Azure Storage operation fails."""
    
    def __init__(self, error: str):
        super().__init__("Azure Storage", error)


class RateLimitException(ExternalAPIException):
    """Raised when API rate limit is hit."""
    
    def __init__(self, provider: str, retry_after: int = None):
        self.provider = provider
        self.retry_after = retry_after
        msg = f"{provider} rate limit exceeded"
        if retry_after:
            msg += f". Retry after {retry_after}s"
        super().__init__(msg)


class TimeoutException(ExternalAPIException):
    """Raised when operation times out."""
    
    def __init__(self, operation: str, timeout: float):
        self.operation = operation
        self.timeout = timeout
        super().__init__(f"{operation} timed out after {timeout}s")


# Validation exceptions

class ValidationException(DomainException):
    """Raised when validation fails."""
    
    def __init__(self, message: str, field: str = None):
        self.field = field
        super().__init__(message)


class RequestTooLargeException(ValidationException):
    """Raised when request payload exceeds size limits."""
    
    def __init__(self, size_mb: float, max_mb: int):
        self.size_mb = size_mb
        self.max_mb = max_mb
        super().__init__(
            f"Request too large ({size_mb:.2f}MB). Maximum allowed: {max_mb}MB",
            field="request_body"
        )


class FileTooLargeException(ValidationException):
    """Raised when uploaded file exceeds size limits."""
    
    def __init__(self, file_name: str, size_mb: float, max_mb: int):
        self.file_name = file_name
        self.size_mb = size_mb
        self.max_mb = max_mb
        super().__init__(
            f"File '{file_name}' is too large ({size_mb:.2f}MB). Maximum allowed: {max_mb}MB",
            field="file"
        )


class MessageTooLongException(ValidationException):
    """Raised when message exceeds length limits."""
    
    def __init__(self, length: int, max_length: int):
        self.length = length
        self.max_length = max_length
        super().__init__(
            f"Message too long ({length:,} characters). Maximum allowed: {max_length:,} characters",
            field="message"
        )


class TooManyFilesException(ValidationException):
    """Raised when upload batch exceeds file count limits."""
    
    def __init__(self, count: int, max_count: int):
        self.count = count
        self.max_count = max_count
        super().__init__(
            f"Too many files ({count}). Maximum allowed: {max_count} files per upload",
            field="files"
        )


class CheckpointNotFoundException(NotFoundException):
    """Raised when a checkpoint is not found."""

    def __init__(self, checkpoint_id: str):
        self.checkpoint_id = checkpoint_id
        super().__init__(f"Checkpoint {checkpoint_id} not found")


class RevertConflictException(DomainException):
    """Raised when revert cannot proceed due to a running execution."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(
            f"Cannot revert session {session_id}: an execution is currently running"
        )


class ConfigurationException(Exception):
    """Raised when configuration is invalid."""
    pass
