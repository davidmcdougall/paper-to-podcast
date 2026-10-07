"""Two provider capabilities: text and speech. No import-time I/O."""
import hashlib
from credential_store import endpoint_identity


def cache_scope(endpoint, credential):
    """In-memory identity changes with endpoint or resolved credential revision."""
    return (endpoint_identity('anthropic', endpoint),
            hashlib.sha256((credential or '').encode()).hexdigest())
