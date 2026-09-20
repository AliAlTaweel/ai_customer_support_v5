"""Splits text into overlapping chunks sized for embedding + retrieval."""


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split text into overlapping word-based chunks.

    chunk_size and overlap are measured in words, not characters, to keep
    chunk boundaries readable and avoid splitting mid-word.

    Raises:
        ValueError: if chunk_size <= 0, overlap < 0, or overlap >= chunk_size.
            An overlap that is not strictly smaller than chunk_size would
            leave the sliding window unable to advance (or advancing
            backwards), causing an infinite loop.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    if overlap < 0:
        raise ValueError(f"overlap must be non-negative, got {overlap}")
    if overlap >= chunk_size:
        raise ValueError(
            f"overlap ({overlap}) must be smaller than chunk_size ({chunk_size})"
        )

    words = text.split()
    if not words:
        return []

    if len(words) <= chunk_size:
        return [text.strip()]

    chunks = []
    start = 0
    step = chunk_size - overlap
    while start < len(words):
        chunk_words = words[start:start + chunk_size]
        chunks.append(" ".join(chunk_words))
        if start + chunk_size >= len(words):
            break
        start += step

    return chunks
