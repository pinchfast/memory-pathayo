from fastapi import APIRouter, Depends, HTTPException, status

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .schemas import PersonCreate, PersonRead, PersonSummary
from .service import get_contributions, get_person, get_store, list_people, upsert_person

router = APIRouter(prefix="/people", tags=["people"])


@router.post(
    "/",
    response_model=PersonRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update a team member",
    description=(
        "Create a person profile (or update an existing one by name). Stores role, "
        "title, skills, languages, and technical flag in the graph. Skills are used "
        "for task assignment recommendations."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def create_person(payload: PersonCreate, org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    await upsert_person(store, payload.model_dump())
    person = await get_person(store, payload.name)
    return PersonRead(**person)


@router.get(
    "/",
    response_model=list[PersonSummary],
    summary="List team members with reliability scores",
    description=(
        "List all team members with a summary including skill count, commitment "
        "history, and a reliability score (0.0–1.0) derived from their "
        "commitment/completion/performance facts."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def list_people_endpoint(org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    return [PersonSummary(**p) for p in await list_people(store)]


@router.get(
    "/{name}",
    response_model=PersonRead,
    summary="Get a team member's full profile",
    description=(
        "Get a person's profile, their recent facts (commitments, status updates, "
        "performance signals), and a detailed reliability breakdown."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def get_person_endpoint(name: str, org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    person = await get_person(store, name)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    return PersonRead(**person)


@router.get(
    "/{name}/contributions",
    summary="Get a person's contribution profile",
    description=(
        "Get a full contribution timeline for a team member — what they've done "
        "over time, grouped by project and fact kind. Includes fulfilled "
        "commitments count, recent activity timeline, and per-project breakdown."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def get_contributions_endpoint(name: str, org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    person = await get_person(store, name)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    return await get_contributions(store, name)
