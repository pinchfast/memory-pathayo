from fastapi import APIRouter, Depends, HTTPException, status

from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .schemas import PersonCreate, PersonRead, PersonSummary
from .service import get_person, get_store, list_people, upsert_person

router = APIRouter(prefix="/people", tags=["people"])


@router.post("/", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
async def create_person(payload: PersonCreate, org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    await upsert_person(store, payload.model_dump())
    person = await get_person(store, payload.name)
    return PersonRead(**person)


@router.get("/", response_model=list[PersonSummary])
async def list_people_endpoint(org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    return [PersonSummary(**p) for p in await list_people(store)]


@router.get("/{name}", response_model=PersonRead)
async def get_person_endpoint(name: str, org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    person = await get_person(store, name)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    return PersonRead(**person)
