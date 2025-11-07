# type: ignore
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Template,
    TemplateCreate,
    TemplatePublic,
    TemplatesPublic,
    TemplateUpdate,
    Message,
)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("/", response_model=TemplatesPublic)
def read_templates(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
    tag: str | None = Query(default=None, description="Filter templates by tag"),
    default_only: bool = Query(default=False, description="Return only default templates"),
) -> Any:
    """
    Retrieve templates.
    
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return
    - **tag**: Filter by template tag (e.g., 'custom', 'marketing', 'notification')
    - **default_only**: If true, return only default templates
    """

    if current_user.is_superuser:
        # Superusers can see all templates
        count_statement = select(func.count()).select_from(Template)
        statement = select(Template)
    else:
        # Regular users can only see their own templates
        count_statement = (
            select(func.count())
            .select_from(Template)
            .where(Template.owner_id == current_user.id)
        )
        statement = select(Template).where(Template.owner_id == current_user.id)

    # Apply filters
    if tag:
        count_statement = count_statement.where(Template.tag == tag)
        statement = statement.where(Template.tag == tag)
    
    if default_only:
        count_statement = count_statement.where(Template.default == True)
        statement = statement.where(Template.default == True)

    # Get count
    count = session.exec(count_statement).one()

    # Apply pagination and ordering
    statement = statement.order_by(Template.created_at.desc()).offset(skip).limit(limit)
    templates = session.exec(statement).all()

    return TemplatesPublic(data=templates, count=count)  # type: ignore


@router.get("/{id}", response_model=TemplatePublic)
def read_template(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Any:
    """
    Get template by ID.
    """
    template = session.get(Template, id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not current_user.is_superuser and (template.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return template


@router.get("/by-tag/{tag}", response_model=TemplatesPublic)
def read_templates_by_tag(
    session: SessionDep,
    current_user: CurrentUser,
    tag: str,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Get templates by tag.
    
    Useful for grouping templates by categories like:
    - 'marketing': Marketing campaign templates
    - 'notification': System notification templates
    - 'alert': Alert message templates
    - 'custom': User-created custom templates
    """
    if current_user.is_superuser:
        count_statement = (
            select(func.count())
            .select_from(Template)
            .where(Template.tag == tag)
        )
        statement = (
            select(Template)
            .where(Template.tag == tag)
            .order_by(Template.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
    else:
        count_statement = (
            select(func.count())
            .select_from(Template)
            .where(Template.owner_id == current_user.id)
            .where(Template.tag == tag)
        )
        statement = (
            select(Template)
            .where(Template.owner_id == current_user.id)
            .where(Template.tag == tag)
            .order_by(Template.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

    count = session.exec(count_statement).one()
    templates = session.exec(statement).all()

    return TemplatesPublic(data=templates, count=count)  # type: ignore


@router.get("/defaults/list", response_model=TemplatesPublic)
def read_default_templates(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Get all default templates for the current user.
    
    Default templates are pre-configured templates that users frequently use.
    """
    count_statement = (
        select(func.count())
        .select_from(Template)
        .where(Template.owner_id == current_user.id)
        .where(Template.default == True)
    )
    count = session.exec(count_statement).one()

    statement = (
        select(Template)
        .where(Template.owner_id == current_user.id)
        .where(Template.default == True)
        .order_by(Template.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    templates = session.exec(statement).all()

    return TemplatesPublic(data=templates, count=count)  # type: ignore


@router.post("/", response_model=TemplatePublic)
def create_template(
    *, session: SessionDep, current_user: CurrentUser, template_in: TemplateCreate
) -> Any:
    """
    Create new template.
    
    Templates can be used to store frequently used SMS messages.
    """
    # Check if user is trying to create a default template when they already have one
    if template_in.default:
        existing_default = session.exec(
            select(Template)
            .where(Template.owner_id == current_user.id)
            .where(Template.default == True)
        ).first()
        
        if existing_default:
            raise HTTPException(
                status_code=400,
                detail="You already have a default template. Please unset the existing default template first.",
            )

    template = Template.model_validate(template_in, update={"owner_id": current_user.id})
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.put("/{id}", response_model=TemplatePublic)
def update_template(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    template_in: TemplateUpdate,
) -> Any:
    """
    Update a template.
    """
    template = session.get(Template, id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not current_user.is_superuser and (template.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    # If trying to set as default, check if another default exists
    if template_in.default and not template.default:
        existing_default = session.exec(
            select(Template)
            .where(Template.owner_id == current_user.id)
            .where(Template.default == True)
            .where(Template.id != id)
        ).first()
        
        if existing_default:
            raise HTTPException(
                status_code=400,
                detail=f"Template '{existing_default.name}' is already set as default. Please unset it first.",
            )

    update_dict = template_in.model_dump(exclude_unset=True)
    template.sqlmodel_update(update_dict)
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.patch("/{id}/set-default", response_model=TemplatePublic)
def set_template_as_default(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Any:
    """
    Set a template as the default template.
    
    This will unset any existing default template automatically.
    """
    template = session.get(Template, id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not current_user.is_superuser and (template.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    # Unset any existing default templates
    existing_defaults = session.exec(
        select(Template)
        .where(Template.owner_id == current_user.id)
        .where(Template.default == True)
        .where(Template.id != id)
    ).all()
    
    for default_template in existing_defaults:
        default_template.default = False
        session.add(default_template)

    # Set this template as default
    template.default = True
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.patch("/{id}/unset-default", response_model=TemplatePublic)
def unset_template_as_default(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Any:
    """
    Unset a template as the default template.
    """
    template = session.get(Template, id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not current_user.is_superuser and (template.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    template.default = False
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.delete("/{id}")
def delete_template(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Delete a template.
    """
    template = session.get(Template, id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not current_user.is_superuser and (template.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    session.delete(template)
    session.commit()
    return Message(message="Template deleted successfully")


@router.get("/tags/list", response_model=list[str])
def get_template_tags(
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Get all unique template tags for the current user.
    
    Useful for filtering and organizing templates.
    """
    if current_user.is_superuser:
        statement = select(Template.tag).distinct()
    else:
        statement = (
            select(Template.tag)
            .where(Template.owner_id == current_user.id)
            .distinct()
        )
    
    tags = session.exec(statement).all()
    return [tag for tag in tags if tag]  # Filter out None values