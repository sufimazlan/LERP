"""Time-ordered UUIDv7 primary keys (RFC 9562).

Generated in Python so they work on any PostgreSQL version; PostgreSQL 18's native
uuidv7() produces the same layout. Time-ordered keys index well, and they never
collide when a tenant is copied from the shared database into its own.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    if hasattr(uuid, "uuid7"):  # Python 3.14+
        return uuid.uuid7()
    unix_ms = time.time_ns() // 1_000_000
    value = (unix_ms & ((1 << 48) - 1)) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC 9562 variant
    return uuid.UUID(int=value)
