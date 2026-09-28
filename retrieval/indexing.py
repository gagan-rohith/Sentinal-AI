"""Build the knowledge index.

Usage: python -m retrieval.indexing [--recreate]

Indexed sources:
- runbooks, one chunk per section so each chunk fits the embedding model's window
- resolved incidents, including their recorded root cause and remediation (postmortem data)
- service documentation
- error log snippets captured during each resolved incident

Open incidents are not indexed: they are the questions, not the knowledge.
"""

import argparse
import asyncio
import re
from datetime import timedelta
from pathlib import Path

import structlog

from core.enums import IncidentStatus, SourceType
from core.models import Incident
from data import DATA_DIR
from data.loader import Runbook, ServiceDoc, load_incidents, load_runbooks, load_service_docs
from retrieval.backend import SearchBackend
from retrieval.embeddings import EmbeddingProvider
from retrieval.models import SearchDocument
from tools.backend import SimulatedOpsBackend
from tools.logs import summarize_errors

log = structlog.get_logger(__name__)

EMBED_BATCH = 64


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def runbook_documents(runbook: Runbook) -> list[SearchDocument]:
    docs = []
    for section in re.split(r"^## ", runbook.body, flags=re.MULTILINE)[1:]:
        heading, _, content = section.partition("\n")
        heading = heading.strip()
        docs.append(
            SearchDocument(
                document_id=f"runbook:{runbook.runbook_id}:{_slug(heading)}",
                parent_id=f"runbook:{runbook.runbook_id}",
                source_type=SourceType.RUNBOOK,
                title=f"{runbook.title}: {heading}",
                text=f"{runbook.title}. {heading}.\n{content.strip()}",
                tags=runbook.tags,
                metadata={
                    "runbook_id": runbook.runbook_id,
                    "section": heading,
                    "actions": runbook.actions,
                },
            )
        )
    return docs


def incident_document(incident: Incident) -> SearchDocument:
    text = "\n".join(
        [
            incident.search_text(),
            f"Root cause: {incident.ground_truth_root_cause}",
            f"Remediation: {incident.expected_remediation}",
        ]
    )
    return SearchDocument(
        document_id=f"incident:{incident.incident_id}",
        parent_id=f"incident:{incident.incident_id}",
        source_type=SourceType.INCIDENT,
        title=incident.title,
        text=text,
        service=incident.service,
        environment=incident.environment,
        severity=incident.severity,
        timestamp=incident.timestamp,
        incident_id=incident.incident_id,
        tags=incident.tags,
        metadata={
            "incident_id": incident.incident_id,
            "root_cause_category": incident.root_cause_category,
            "runbook_ids": incident.relevant_runbook_ids,
            "root_cause": incident.ground_truth_root_cause,
            "remediation": incident.expected_remediation,
        },
    )


def service_document(doc: ServiceDoc) -> SearchDocument:
    return SearchDocument(
        document_id=f"service_doc:{doc.service}",
        parent_id=f"service_doc:{doc.service}",
        source_type=SourceType.SERVICE_DOC,
        title=f"{doc.service} service documentation",
        text=doc.body,
        service=doc.service,
        tags=doc.tags,
        metadata={"team": doc.team, "namespace": doc.namespace},
    )


def log_document(incident: Incident, ops: SimulatedOpsBackend) -> SearchDocument | None:
    entries = ops.logs(
        incident.service, incident.timestamp - timedelta(minutes=30), incident.timestamp
    )
    patterns = summarize_errors(entries, top=5)
    if not patterns:
        return None
    lines = [f"[{p.level}] x{p.count} {p.example}" for p in patterns]
    return SearchDocument(
        document_id=f"log:{incident.incident_id}",
        parent_id=f"log:{incident.incident_id}",
        source_type=SourceType.LOG,
        title=f"Error logs from {incident.service} during {incident.incident_id}",
        text="\n".join(lines),
        service=incident.service,
        environment=incident.environment,
        severity=incident.severity,
        timestamp=incident.timestamp,
        incident_id=incident.incident_id,
        tags=incident.tags,
        metadata={"incident_id": incident.incident_id},
    )


def build_documents(
    root: Path = DATA_DIR, ops: SimulatedOpsBackend | None = None
) -> list[SearchDocument]:
    ops = ops or SimulatedOpsBackend.from_data_dir(root)
    history = [i for i in load_incidents(root) if i.status is IncidentStatus.RESOLVED]

    docs: list[SearchDocument] = []
    for runbook in load_runbooks(root):
        docs.extend(runbook_documents(runbook))
    docs.extend(service_document(d) for d in load_service_docs(root))
    for incident in history:
        docs.append(incident_document(incident))
        snippet = log_document(incident, ops)
        if snippet:
            docs.append(snippet)
    return docs


async def ingest(
    backend: SearchBackend,
    embedder: EmbeddingProvider,
    docs: list[SearchDocument],
    *,
    recreate: bool = False,
) -> int:
    await backend.ensure_index(embedder.dimensions, recreate=recreate)
    embedded: list[SearchDocument] = []
    for start in range(0, len(docs), EMBED_BATCH):
        batch = docs[start : start + EMBED_BATCH]
        vectors = await asyncio.to_thread(
            embedder.embed_documents, [f"{d.title}\n{d.text}" for d in batch]
        )
        embedded.extend(
            d.model_copy(update={"embedding": v}) for d, v in zip(batch, vectors, strict=True)
        )
    count = await backend.index_documents(embedded)
    log.info("index_built", backend=backend.name, documents=count, embedder=embedder.name)
    return count


async def _main(recreate: bool) -> None:
    from app.config import get_settings
    from retrieval.factory import create_search_backend, embedder_from_settings

    settings = get_settings()
    backend = create_search_backend(settings)
    try:
        docs = build_documents(settings.data_dir)
        count = await ingest(backend, embedder_from_settings(settings), docs, recreate=recreate)
        print(f"indexed {count} documents into {backend.name}")
    finally:
        await backend.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recreate", action="store_true", help="drop and rebuild the index")
    args = parser.parse_args()
    asyncio.run(_main(args.recreate))


if __name__ == "__main__":
    main()
