"""Small in-process BM25 index for the six policy documents."""

from __future__ import annotations

import math
import re
from collections import Counter

from agentdesk.retrieval.documents import PolicySection


TOKEN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "do",
    "for",
    "i",
    "is",
    "it",
    "my",
    "of",
    "the",
    "to",
    "what",
    "you",
}


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN.findall(text.lower())
        if token not in STOP_WORDS
    ]


class BM25Index:
    def __init__(
        self,
        sections: list[PolicySection],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.sections = sections
        self.k1 = k1
        self.b = b
        self.documents = [
            tokenize(f"{section.title} {section.text}") for section in sections
        ]
        self.counts = [Counter(document) for document in self.documents]
        self.average_length = (
            sum(len(document) for document in self.documents) / len(self.documents)
            if self.documents
            else 0
        )
        self.document_frequency = Counter(
            term for document in self.documents for term in set(document)
        )

    def search(
        self, query: str, *, limit: int = 5
    ) -> list[tuple[PolicySection, float]]:
        query_terms = tokenize(query)
        if not query_terms or not self.sections:
            return []
        scored: list[tuple[PolicySection, float]] = []
        total = len(self.sections)
        for section, document, counts in zip(
            self.sections, self.documents, self.counts, strict=True
        ):
            score = 0.0
            matched_terms = sum(1 for term in set(query_terms) if counts[term] > 0)
            if matched_terms / len(set(query_terms)) < 0.5:
                continue
            length_ratio = (
                len(document) / self.average_length if self.average_length else 0
            )
            for term in query_terms:
                frequency = counts[term]
                if frequency == 0:
                    continue
                document_frequency = self.document_frequency[term]
                inverse_frequency = math.log(
                    1 + (total - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * length_ratio
                )
                score += inverse_frequency * (frequency * (self.k1 + 1) / denominator)
            if score > 0:
                scored.append((section, score))
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]
