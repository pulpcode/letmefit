from uuid import uuid4

ID_LENGTH = 40
UUID_HEX_LENGTH = 32
MIN_RANDOM_HEX_LENGTH = 16


def new_id(prefix: str) -> str:
    random_length = min(UUID_HEX_LENGTH, ID_LENGTH - len(prefix) - 1)
    if random_length < MIN_RANDOM_HEX_LENGTH:
        raise ValueError("ID prefix is too long")
    return f"{prefix}_{uuid4().hex[:random_length]}"
