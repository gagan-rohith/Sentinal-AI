import re

from pydantic import BaseModel, Field

from core.exceptions import NotFoundError
from data.loader import Runbook


class RunbookQuery(BaseModel):
    runbook_id: str = Field(pattern=r"^[a-z0-9-]+$")


class RunbookDocument(BaseModel):
    runbook_id: str
    title: str
    actions: list[str]
    sections: dict[str, str]


class RunbookLibrary:
    def __init__(self, runbooks: list[Runbook]) -> None:
        self._runbooks = {r.runbook_id: r for r in runbooks}

    async def get(self, query: RunbookQuery) -> RunbookDocument:
        runbook = self._runbooks.get(query.runbook_id)
        if runbook is None:
            raise NotFoundError(f"runbook '{query.runbook_id}' not found")
        sections = {}
        for block in re.split(r"^## ", runbook.body, flags=re.MULTILINE)[1:]:
            heading, _, content = block.partition("\n")
            sections[heading.strip()] = content.strip()
        return RunbookDocument(
            runbook_id=runbook.runbook_id,
            title=runbook.title,
            actions=runbook.actions,
            sections=sections,
        )
