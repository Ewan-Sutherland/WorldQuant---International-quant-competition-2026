"""
Storage factory - returns the right Storage backend based on config.

Usage:
    from storage_factory import get_storage
    storage = get_storage()
"""
import config


def get_storage():
    """Return a Storage instance using the configured backend."""
    if config.STORAGE_BACKEND == "supabase":
        from storage_supabase import Storage
        return Storage(
            supabase_url=config.SUPABASE_URL,
            supabase_key=config.SUPABASE_ANON_KEY,
            owner=config.BRAIN_USERNAME,
        )
    else:
        from storage import Storage
        return Storage(config.DB_PATH)
