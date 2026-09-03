import re

# A sentence boundary is a period followed by whitespace and the start of
# the next sentence -- a capital letter, or an opening quote around a
# quoted card name. The whitespace itself is consumed by the split (and
# each part is stripped), matching the existing project convention of
# normalizing whitespace rather than preserving it verbatim (see
# clause_splitter._normalize, which this replaces the LLM-facing half of).
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.])\s+(?=[A-Z"])')


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
