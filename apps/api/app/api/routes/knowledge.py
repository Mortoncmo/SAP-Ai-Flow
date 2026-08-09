from fastapi import APIRouter, Depends

from app.api.routes.projects import get_repository
from app.db.repository import BlueprintRepository
from app.knowledge.service import KnowledgeService, get_knowledge_service
from app.models.knowledge import (
    GapAnalyzeRequest,
    GapAnalyzeResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.security.auth import (
    ProjectRole,
    UserContext,
    get_user_context,
    require_development_mode,
    require_role,
)

router = APIRouter(prefix="/api/v1", tags=["knowledge"])


@router.post("/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    request: KnowledgeSearchRequest,
    _: None = Depends(require_development_mode),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeSearchResponse:
    return service.search(request)


@router.post(
    "/projects/{project_id}/knowledge/search",
    response_model=KnowledgeSearchResponse,
)
def search_project_knowledge(
    project_id: str,
    request: KnowledgeSearchRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> KnowledgeSearchResponse:
    _require_editor(repository, project_id, user)
    return service.search(request)


@router.post("/gaps/analyze", response_model=GapAnalyzeResponse)
def analyze_gap(
    request: GapAnalyzeRequest,
    _: None = Depends(require_development_mode),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> GapAnalyzeResponse:
    return service.analyze_gap(request)


@router.post(
    "/projects/{project_id}/gaps/analyze",
    response_model=GapAnalyzeResponse,
)
def analyze_project_gap(
    project_id: str,
    request: GapAnalyzeRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> GapAnalyzeResponse:
    _require_editor(repository, project_id, user)
    return service.analyze_gap(request)


def _require_editor(
    repository: BlueprintRepository, project_id: str, user: UserContext
) -> None:
    repository.require_project(project_id, user_id=user.user_id)
    membership = repository.require_project_member(project_id, user.user_id)
    require_role(ProjectRole(membership.role), ProjectRole.EDITOR)
