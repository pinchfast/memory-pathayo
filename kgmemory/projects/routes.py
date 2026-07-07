from fastapi import APIRouter, Depends, HTTPException, Query, status

from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .schemas import (
    AssignmentRecommendation,
    ProjectCreate,
    ProjectRead,
    TaskCreate,
    TaskRead,
)
from .service import (
    assign_task,
    get_store,
    list_projects,
    list_tasks,
    recommend_assignees,
    upsert_project,
    upsert_task,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    await upsert_project(store, payload.model_dump())
    return ProjectRead(
        name=payload.name,
        description=payload.description,
        status=payload.status,
        deadline=payload.deadline,
        task_count=0,
        open_task_count=0,
        member_count=0,
    )


@router.get("/", response_model=list[ProjectRead])
async def list_projects_endpoint(org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    return [ProjectRead(**p) for p in await list_projects(store)]


@router.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, org: Organization = Depends(get_current_org)):
    store = await get_store(org.graph_name)
    task_id = await upsert_task(store, payload.model_dump())
    return TaskRead(
        task_id=task_id,
        title=payload.title,
        project=payload.project,
        status="open",
        required_skills=payload.required_skills,
        estimated_days=payload.estimated_days,
        deadline=payload.deadline,
        assignee=None,
    )


@router.get("/tasks", response_model=list[TaskRead])
async def list_tasks_endpoint(
    org: Organization = Depends(get_current_org),
    project: str | None = Query(None, max_length=200),
):
    store = await get_store(org.graph_name)
    return [TaskRead(**t) for t in await list_tasks(store, project)]


@router.get("/tasks/{task_id}/recommendations", response_model=AssignmentRecommendation)
async def assignment_recommendations(
    task_id: str, org: Organization = Depends(get_current_org)
):
    store = await get_store(org.graph_name)
    tasks = await list_tasks(store)
    task = next((t for t in tasks if t["task_id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    recommendations = await recommend_assignees(store, task_id)
    return AssignmentRecommendation(task=TaskRead(**task), recommendations=recommendations)


@router.post("/tasks/{task_id}/assign", response_model=TaskRead)
async def assign_task_endpoint(
    task_id: str, person: str = Query(..., max_length=200), org: Organization = Depends(get_current_org)
):
    store = await get_store(org.graph_name)
    await assign_task(store, task_id, person)
    tasks = await list_tasks(store)
    task = next((t for t in tasks if t["task_id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskRead(**task)
