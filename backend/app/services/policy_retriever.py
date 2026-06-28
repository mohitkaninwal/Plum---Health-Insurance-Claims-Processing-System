from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import PolicyKnowledgeChunkRecord
from app.db.session import SessionLocal
from app.models.contracts import ClaimCategory, ClaimSubmission, PolicyEvidence
from app.models.policy import PolicyTerms

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DOCUMENTS_GUIDE_PATH = REPO_ROOT / "sample_documents_guide.md"
EMBEDDING_DIMENSIONS = 384  # all-MiniLM-L6-v2 output dimension
RRF_K = 60

_sentence_model = None
_sentence_model_loaded = False
_MODEL_LOCK = threading.Lock()


def _get_sentence_model():
    """Return the sentence-transformer model, or None if embeddings are disabled.

    sentence-transformers pulls in PyTorch which consumes 300–450 MB of RSS on
    Linux.  When ``ENABLE_EMBEDDINGS`` is False (the default) we skip the import
    entirely and the SHA-256 fallback in ``embed_text`` is used instead.

    To enable real semantic embeddings set ``ENABLE_EMBEDDINGS=true`` in the
    environment.  Only do this on instances with at least 1 GB of available RAM
    (Render Standard plan or equivalent).
    """
    global _sentence_model, _sentence_model_loaded
    if _sentence_model_loaded:
        return _sentence_model
    with _MODEL_LOCK:
        if _sentence_model_loaded:
            return _sentence_model
        _sentence_model_loaded = True
    if not settings.enable_embeddings:
        # Fast path: skip torch import entirely to keep RSS well below 512 MB.
        _sentence_model = None
        return None
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        _sentence_model = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _sentence_model = None
    return _sentence_model


@dataclass(frozen=True)
class KnowledgeChunk:
    evidence_id: str
    source: str
    source_path: str
    rule_category: str
    text: str
    claim_category: ClaimCategory | None = None
    keywords: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


def build_policy_knowledge_base(
    policy: PolicyTerms,
    guide_path: Path = SAMPLE_DOCUMENTS_GUIDE_PATH,
) -> list[KnowledgeChunk]:
    chunks = _policy_json_chunks(policy)
    # sample_documents_guide.md is a development reference for extraction formats,
    # not policy rules — excluded from the knowledge base to keep evidence relevant.
    return [
        KnowledgeChunk(
            evidence_id=chunk.evidence_id,
            source=chunk.source,
            source_path=chunk.source_path,
            rule_category=chunk.rule_category,
            claim_category=chunk.claim_category,
            text=chunk.text,
            keywords=chunk.keywords or _keywords(chunk.text),
            metadata=chunk.metadata,
            embedding=embed_text(chunk.text),
        )
        for chunk in chunks
    ]


def index_policy_knowledge(
    db: Session,
    policy: PolicyTerms,
    guide_path: Path = SAMPLE_DOCUMENTS_GUIDE_PATH,
) -> list[KnowledgeChunk]:
    chunks = build_policy_knowledge_base(policy, guide_path)
    db.execute(delete(PolicyKnowledgeChunkRecord).where(PolicyKnowledgeChunkRecord.policy_id == policy.policy_id))
    db.add_all(
        PolicyKnowledgeChunkRecord(
            policy_id=policy.policy_id,
            evidence_id=chunk.evidence_id,
            source=chunk.source,
            source_path=chunk.source_path,
            rule_category=chunk.rule_category,
            claim_category=str(chunk.claim_category) if chunk.claim_category else None,
            text=chunk.text,
            keywords=chunk.keywords,
            embedding=chunk.embedding,
            metadata_json=chunk.metadata,
        )
        for chunk in chunks
    )
    return chunks


def index_policy_knowledge_on_startup(policy: PolicyTerms) -> None:
    if SessionLocal is None:
        return

    db = SessionLocal()
    try:
        index_policy_knowledge(db, policy)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        db.close()


def retrieve_policy_evidence(
    submission: ClaimSubmission,
    policy: PolicyTerms,
    *,
    limit: int = 5,
) -> list[PolicyEvidence]:
    query = _submission_query(submission)
    if SessionLocal is not None:
        db = SessionLocal()
        try:
            evidence = _retrieve_from_db(db, policy.policy_id, submission.claim_category, query, limit)
            if evidence:
                return evidence
        except SQLAlchemyError:
            return _retrieve_from_memory(submission, policy, query, limit)
        finally:
            db.close()

    return _retrieve_from_memory(submission, policy, query, limit)


def reciprocal_rank_fusion(
    dense_ids: list[str],
    lexical_ids: list[str],
    *,
    k: int = RRF_K,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in (dense_ids, lexical_ids):
        for rank, evidence_id in enumerate(ranking, start=1):
            scores[evidence_id] = scores.get(evidence_id, 0.0) + 1.0 / (k + rank)
    return scores


def embed_text(text_value: str, *, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    model = _get_sentence_model()
    if model is not None:
        try:
            embedding = model.encode(text_value, normalize_embeddings=True)
            return [round(float(v), 6) for v in embedding[:dimensions]]
        except Exception:
            pass
    return _sha256_embed(text_value, dimensions=dimensions)


def _sha256_embed(text_value: str, *, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """Deterministic fallback embedding using SHA-256 token hashing."""
    vector = [0.0] * dimensions
    tokens = _keywords(text_value)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def _policy_json_chunks(policy: PolicyTerms) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for category, requirement in policy.document_requirements.items():
        chunks.append(
            _chunk(
                evidence_id=f"POLICY_DOCUMENT_REQUIREMENTS_{category}",
                source_path=f"document_requirements.{category}",
                rule_category="document_requirements",
                claim_category=category,
                payload=requirement.model_dump(mode="json"),
                intro=f"{category} required and optional document rules.",
            )
        )

    for category_key, config in policy.opd_categories.items():
        claim_category = ClaimCategory(category_key.upper())
        chunks.append(
            _chunk(
                evidence_id=f"POLICY_OPD_CATEGORY_{claim_category}",
                source_path=f"opd_categories.{category_key}",
                rule_category="opd_category",
                claim_category=claim_category,
                payload=config.model_dump(mode="json"),
                intro=f"{claim_category} coverage, limits, co-pay, and pre-authorization rules.",
            )
        )

    chunks.append(
        _chunk(
            evidence_id="POLICY_COVERAGE_LIMITS",
            source_path="coverage",
            rule_category="coverage_limits",
            payload=policy.coverage.model_dump(mode="json"),
            intro="Policy coverage limits including annual OPD and per-claim limits.",
        )
    )
    chunks.append(
        _chunk(
            evidence_id="POLICY_WAITING_PERIODS",
            source_path="waiting_periods",
            rule_category="waiting_periods",
            payload=policy.waiting_periods.model_dump(mode="json"),
            intro="Initial, pre-existing, and specific condition waiting period rules.",
        )
    )
    chunks.append(
        _chunk(
            evidence_id="POLICY_EXCLUSIONS",
            source_path="exclusions",
            rule_category="exclusions",
            payload=policy.exclusions.model_dump(mode="json"),
            intro="Policy condition, dental, and vision exclusions.",
        )
    )
    chunks.append(
        _chunk(
            evidence_id="POLICY_PRE_AUTHORIZATION",
            source_path="pre_authorization",
            rule_category="pre_authorization",
            payload=policy.pre_authorization.model_dump(mode="json"),
            intro="Policy pre-authorization requirements and validity.",
        )
    )
    chunks.append(
        _chunk(
            evidence_id="POLICY_SUBMISSION_RULES",
            source_path="submission_rules",
            rule_category="submission_rules",
            payload=policy.submission_rules.model_dump(mode="json"),
            intro="Claim submission deadline, minimum amount, and currency rules.",
        )
    )
    chunks.append(
        _chunk(
            evidence_id="POLICY_FRAUD_THRESHOLDS",
            source_path="fraud_thresholds",
            rule_category="fraud_thresholds",
            payload=policy.fraud_thresholds.model_dump(mode="json"),
            intro="Fraud and manual review threshold rules.",
        )
    )
    chunks.append(
        _chunk(
            evidence_id="POLICY_NETWORK_HOSPITALS",
            source_path="network_hospitals",
            rule_category="network_hospitals",
            payload=policy.network_hospitals,
            intro="Network hospitals eligible for configured discounts.",
        )
    )
    return chunks


def _sample_document_chunks(guide_path: Path) -> list[KnowledgeChunk]:
    if not guide_path.exists():
        return []

    chunks: list[KnowledgeChunk] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in guide_path.read_text(encoding="utf-8").splitlines():
        heading_match = re.match(r"^###\s+(?:\d+\.\s*)?(?P<title>.+)$", line)
        if heading_match:
            _append_markdown_chunk(chunks, current_heading, current_lines)
            current_heading = heading_match.group("title").strip()
            current_lines = [line]
            continue
        if current_heading is not None:
            current_lines.append(line)

    _append_markdown_chunk(chunks, current_heading, current_lines)
    return chunks


def _append_markdown_chunk(
    chunks: list[KnowledgeChunk],
    heading: str | None,
    lines: list[str],
) -> None:
    if not heading or not lines:
        return

    text_value = "\n".join(lines).strip()
    normalized_heading = re.sub(r"[^A-Z0-9]+", "_", heading.upper()).strip("_")
    chunks.append(
        KnowledgeChunk(
            evidence_id=f"DOC_GUIDE_{normalized_heading}",
            source="sample_documents_guide.md",
            source_path=f"document_types.{heading}",
            rule_category="document_extraction",
            text=text_value,
            keywords=_keywords(f"{heading} {text_value}"),
            metadata={"heading": heading},
        )
    )


def _chunk(
    *,
    evidence_id: str,
    source_path: str,
    rule_category: str,
    payload: Any,
    intro: str,
    claim_category: ClaimCategory | None = None,
) -> KnowledgeChunk:
    text_value = f"{intro}\nJSON path: {source_path}\n{json.dumps(payload, sort_keys=True)}"
    return KnowledgeChunk(
        evidence_id=evidence_id,
        source="policy_terms.json",
        source_path=source_path,
        rule_category=rule_category,
        claim_category=claim_category,
        text=text_value,
        keywords=_keywords(text_value),
        metadata={"json_path": source_path},
    )


def _retrieve_from_db(
    db: Session,
    policy_id: str,
    claim_category: ClaimCategory,
    query: str,
    limit: int,
) -> list[PolicyEvidence]:
    query_embedding = embed_text(query)
    dense_rows = db.execute(
        text(
            """
            SELECT evidence_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS dense_score
            FROM policy_knowledge_chunks
            WHERE policy_id = :policy_id
              AND (claim_category IS NULL OR claim_category = :claim_category)
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :candidate_limit
            """
        ),
        {
            "policy_id": policy_id,
            "claim_category": str(claim_category),
            "embedding": _vector_literal(query_embedding),
            "candidate_limit": max(limit * 3, 10),
        },
    ).mappings().all()
    lexical_rows = db.execute(
        text(
            """
            SELECT evidence_id, ts_rank_cd(to_tsvector('english', text), plainto_tsquery('english', :query)) AS lexical_score
            FROM policy_knowledge_chunks
            WHERE policy_id = :policy_id
              AND (claim_category IS NULL OR claim_category = :claim_category)
              AND to_tsvector('english', text) @@ plainto_tsquery('english', :query)
            ORDER BY lexical_score DESC
            LIMIT :candidate_limit
            """
        ),
        {
            "policy_id": policy_id,
            "claim_category": str(claim_category),
            "query": query,
            "candidate_limit": max(limit * 3, 10),
        },
    ).mappings().all()

    dense_scores = {str(row["evidence_id"]): float(row["dense_score"]) for row in dense_rows}
    lexical_scores = {str(row["evidence_id"]): float(row["lexical_score"]) for row in lexical_rows}
    fused = reciprocal_rank_fusion(list(dense_scores), list(lexical_scores))
    if not fused:
        return []

    ranked_ids = sorted(fused, key=fused.get, reverse=True)[:limit]
    chunk_rows = db.execute(
        text(
            """
            SELECT evidence_id, source, source_path, rule_category, claim_category, text
            FROM policy_knowledge_chunks
            WHERE policy_id = :policy_id AND evidence_id = ANY(:evidence_ids)
            """
        ),
        {"policy_id": policy_id, "evidence_ids": ranked_ids},
    ).mappings().all()
    rows_by_id = {str(row["evidence_id"]): row for row in chunk_rows}
    return [
        _evidence_from_mapping(rows_by_id[evidence_id], dense_scores, lexical_scores, fused)
        for evidence_id in ranked_ids
        if evidence_id in rows_by_id
    ]


def _retrieve_from_memory(
    submission: ClaimSubmission,
    policy: PolicyTerms,
    query: str,
    limit: int,
) -> list[PolicyEvidence]:
    chunks = [
        chunk
        for chunk in build_policy_knowledge_base(policy)
        if chunk.claim_category is None or chunk.claim_category == submission.claim_category
    ]
    query_embedding = embed_text(query)
    dense_scores = {
        chunk.evidence_id: _cosine_similarity(query_embedding, chunk.embedding) for chunk in chunks
    }
    lexical_scores = {
        chunk.evidence_id: _lexical_score(query, chunk.text, chunk.keywords) for chunk in chunks
    }
    dense_ids = sorted(dense_scores, key=dense_scores.get, reverse=True)
    lexical_ids = [key for key in sorted(lexical_scores, key=lexical_scores.get, reverse=True) if lexical_scores[key] > 0]
    fused = reciprocal_rank_fusion(dense_ids, lexical_ids)
    ranked = sorted(chunks, key=lambda chunk: fused.get(chunk.evidence_id, 0), reverse=True)[:limit]
    return [
        PolicyEvidence(
            evidence_id=chunk.evidence_id,
            source=chunk.source,
            source_path=chunk.source_path,
            rule_category=chunk.rule_category,
            claim_category=chunk.claim_category,
            text=chunk.text,
            dense_score=round(dense_scores.get(chunk.evidence_id, 0), 6),
            lexical_score=round(lexical_scores.get(chunk.evidence_id, 0), 6),
            rrf_score=round(fused.get(chunk.evidence_id, 0), 6),
        )
        for chunk in ranked
    ]


def _evidence_from_mapping(
    row: Any,
    dense_scores: dict[str, float],
    lexical_scores: dict[str, float],
    fused_scores: dict[str, float],
) -> PolicyEvidence:
    evidence_id = str(row["evidence_id"])
    claim_category = row["claim_category"]
    return PolicyEvidence(
        evidence_id=evidence_id,
        source=str(row["source"]),
        source_path=str(row["source_path"]),
        rule_category=str(row["rule_category"]),
        claim_category=ClaimCategory(claim_category) if claim_category else None,
        text=str(row["text"]),
        dense_score=dense_scores.get(evidence_id),
        lexical_score=lexical_scores.get(evidence_id),
        rrf_score=fused_scores.get(evidence_id),
    )


def _submission_query(submission: ClaimSubmission) -> str:
    document_text = " ".join(
        " ".join(
            str(value)
            for value in [
                doc.actual_type,
                doc.declared_type,
                doc.quality,
                doc.content,
                doc.file_name,
            ]
            if value is not None
        )
        for doc in submission.documents
    )
    return (
        f"{submission.claim_category} claim amount {submission.claimed_amount} "
        f"member {submission.member_id} hospital {submission.hospital_name or ''} {document_text}"
    )


def _keywords(text_value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9_]+", text_value.lower())
        if len(token) > 1 and token not in {"and", "the", "for", "with", "from", "this", "that"}
    ]


def _lexical_score(query: str, text_value: str, keywords: list[str]) -> float:
    query_terms = set(_keywords(query))
    if not query_terms:
        return 0.0
    keyword_terms = set(keywords or _keywords(text_value))
    overlap = query_terms & keyword_terms
    return len(overlap) / len(query_terms)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=False))


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"
