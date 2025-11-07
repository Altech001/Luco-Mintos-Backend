# type: ignore
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select, func
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Contact, ContactCreate, ContactUpdate, ContactPublic, ContactsPublic,
    ContactGroup, ContactGroupCreate, ContactGroupUpdate, ContactGroupPublic, ContactGroupsPublic,
    Message
)

router = APIRouter(prefix="/contacts", tags=["contacts"])


# ==================== CONTACT GROUPS ====================

@router.post("/groups", response_model=ContactGroupPublic)
def create_contact_group(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    group_in: ContactGroupCreate
) -> Any:
    """Create a new contact group."""
    group = ContactGroup(
        **group_in.model_dump(),
        user_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    session.add(group)
    session.commit()
    session.refresh(group)
    
    return ContactGroupPublic(**group.model_dump(), contact_count=0)


@router.get("/groups", response_model=ContactGroupsPublic)
def get_contact_groups(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100
) -> Any:
    """Get all contact groups for current user."""
    statement = (
        select(ContactGroup)
        .where(ContactGroup.user_id == current_user.id)
        .offset(skip)
        .limit(limit)
        .order_by(ContactGroup.created_at.desc())
    )
    
    groups = session.exec(statement).all()
    
    # Count contacts for each group
    groups_public = []
    for group in groups:
        contact_count = len(group.contacts) if group.contacts else 0
        groups_public.append(ContactGroupPublic(**group.model_dump(), contact_count=contact_count))
    
    count_statement = select(func.count()).select_from(ContactGroup).where(ContactGroup.user_id == current_user.id)
    count = session.exec(count_statement).one()
    
    return ContactGroupsPublic(data=groups_public, count=count)


@router.get("/groups/{group_id}", response_model=ContactGroupPublic)
def get_contact_group(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    group_id: uuid.UUID
) -> Any:
    """Get a specific contact group."""
    group = session.get(ContactGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Contact group not found")
    
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    contact_count = len(group.contacts) if group.contacts else 0
    return ContactGroupPublic(**group.model_dump(), contact_count=contact_count)


@router.patch("/groups/{group_id}", response_model=ContactGroupPublic)
def update_contact_group(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    group_id: uuid.UUID,
    group_update: ContactGroupUpdate
) -> Any:
    """Update a contact group."""
    group = session.get(ContactGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Contact group not found")
    
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    update_data = group_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(group, key, value)
    
    group.updated_at = datetime.utcnow()
    
    session.add(group)
    session.commit()
    session.refresh(group)
    
    contact_count = len(group.contacts) if group.contacts else 0
    return ContactGroupPublic(**group.model_dump(), contact_count=contact_count)


@router.delete("/groups/{group_id}", response_model=Message)
def delete_contact_group(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    group_id: uuid.UUID
) -> Any:
    """Delete a contact group. Contacts in the group will have group_id set to NULL."""
    group = session.get(ContactGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Contact group not found")
    
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    session.delete(group)
    session.commit()
    
    return Message(message="Contact group deleted successfully")


@router.get("/groups/{group_id}/contacts", response_model=ContactsPublic)
def get_group_contacts(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    group_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100
) -> Any:
    """Get all contacts in a specific group."""
    group = session.get(ContactGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Contact group not found")
    
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    statement = (
        select(Contact)
        .where(Contact.group_id == group_id)
        .offset(skip)
        .limit(limit)
        .order_by(Contact.created_at.desc())
    )
    
    contacts = session.exec(statement).all()
    
    count_statement = select(func.count()).select_from(Contact).where(Contact.group_id == group_id)
    count = session.exec(count_statement).one()
    
    return ContactsPublic(data=contacts, count=count)


# ==================== CONTACTS ====================

@router.post("/", response_model=ContactPublic)
def create_contact(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    contact_in: ContactCreate
) -> Any:
    """Create a new contact."""
    # If group_id is provided, verify it belongs to user
    if contact_in.group_id:
        group = session.get(ContactGroup, contact_in.group_id)
        if not group or group.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Contact group not found")
    
    contact = Contact(
        **contact_in.model_dump(),
        user_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    session.add(contact)
    session.commit()
    session.refresh(contact)
    
    return contact


@router.get("/", response_model=ContactsPublic)
def get_contacts(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
    group_id: uuid.UUID | None = None,
    search: str | None = None
) -> Any:
    """Get all contacts for current user. Filter by group or search."""
    statement = select(Contact).where(Contact.user_id == current_user.id)
    
    if group_id:
        statement = statement.where(Contact.group_id == group_id)
    
    if search:
        search_pattern = f"%{search}%"
        statement = statement.where(
            (Contact.name.ilike(search_pattern)) |
            (Contact.phone.ilike(search_pattern)) |
            (Contact.email.ilike(search_pattern))
        )
    
    statement = statement.offset(skip).limit(limit).order_by(Contact.created_at.desc())
    
    contacts = session.exec(statement).all()
    
    count_statement = select(func.count()).select_from(Contact).where(Contact.user_id == current_user.id)
    if group_id:
        count_statement = count_statement.where(Contact.group_id == group_id)
    if search:
        search_pattern = f"%{search}%"
        count_statement = count_statement.where(
            (Contact.name.ilike(search_pattern)) |
            (Contact.phone.ilike(search_pattern)) |
            (Contact.email.ilike(search_pattern))
        )
    count = session.exec(count_statement).one()
    
    return ContactsPublic(data=contacts, count=count)


@router.get("/{contact_id}", response_model=ContactPublic)
def get_contact(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    contact_id: uuid.UUID
) -> Any:
    """Get a specific contact."""
    contact = session.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    if contact.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    return contact


@router.patch("/{contact_id}", response_model=ContactPublic)
def update_contact(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    contact_id: uuid.UUID,
    contact_update: ContactUpdate
) -> Any:
    """Update a contact."""
    contact = session.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    if contact.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    update_data = contact_update.model_dump(exclude_unset=True)
    
    # If updating group_id, verify it belongs to user
    if "group_id" in update_data and update_data["group_id"]:
        group = session.get(ContactGroup, update_data["group_id"])
        if not group or group.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Contact group not found")
    
    for key, value in update_data.items():
        setattr(contact, key, value)
    
    contact.updated_at = datetime.utcnow()
    
    session.add(contact)
    session.commit()
    session.refresh(contact)
    
    return contact


@router.delete("/{contact_id}", response_model=Message)
def delete_contact(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    contact_id: uuid.UUID
) -> Any:
    """Delete a contact."""
    contact = session.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    if contact.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    session.delete(contact)
    session.commit()
    
    return Message(message="Contact deleted successfully")


@router.post("/bulk-create", response_model=dict)
def bulk_create_contacts(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    contacts_data: list[ContactCreate]
) -> Any:
    """Create multiple contacts at once."""
    created_contacts = []
    errors = []
    
    for idx, contact_data in enumerate(contacts_data):
        try:
            # If group_id is provided, verify it belongs to user
            if contact_data.group_id:
                group = session.get(ContactGroup, contact_data.group_id)
                if not group or group.user_id != current_user.id:
                    errors.append({
                        "index": idx,
                        "error": "Contact group not found"
                    })
                    continue
            
            contact = Contact(
                **contact_data.model_dump(),
                user_id=current_user.id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(contact)
            created_contacts.append(contact)
        except Exception as e:
            errors.append({
                "index": idx,
                "error": str(e)
            })
    
    session.commit()
    
    return {
        "created": len(created_contacts),
        "failed": len(errors),
        "errors": errors
    }


@router.get("/stats/summary", response_model=dict)
def get_contacts_stats(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """Get contact statistics."""
    total_contacts = session.exec(
        select(func.count()).select_from(Contact).where(Contact.user_id == current_user.id)
    ).one()
    
    total_groups = session.exec(
        select(func.count()).select_from(ContactGroup).where(ContactGroup.user_id == current_user.id)
    ).one()
    
    ungrouped_contacts = session.exec(
        select(func.count()).select_from(Contact).where(
            Contact.user_id == current_user.id,
            Contact.group_id == None
        )
    ).one()
    
    return {
        "total_contacts": total_contacts,
        "total_groups": total_groups,
        "ungrouped_contacts": ungrouped_contacts,
        "grouped_contacts": total_contacts - ungrouped_contacts
    }