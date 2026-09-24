"""Retrieval package for user memory search."""

from app.retrieval.models import EvidenceItem, RetrievalResult

__all__ = ["EvidenceItem", "RetrievalResult", "RetrievalService"]


def __getattr__(name):
    if name == "RetrievalService":
        from app.retrieval.retrieval_service import RetrievalService

        return RetrievalService
    raise AttributeError(name)
