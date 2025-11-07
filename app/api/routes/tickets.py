# type: ignore
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select, func
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Ticket, TicketCreate, TicketUpdate, TicketPublic, TicketsPublic,
    TicketResponse, TicketResponseCreate, TicketResponsePublic, TicketResponsesPublic,
    Message
)

router = APIRouter(prefix="/tickets", tags=["tickets"])


# ==================== TICKETS ====================

@router.post("/", response_model=TicketPublic)
def create_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_in: TicketCreate
) -> Any:
    """Create a new support ticket."""
    ticket = Ticket(
        **ticket_in.model_dump(),
        user_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    
    return TicketPublic(**ticket.model_dump(), response_count=0)


@router.get("/", response_model=TicketsPublic)
def get_my_tickets(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None
) -> Any:
    """Get all tickets for current user."""
    statement = select(Ticket).where(Ticket.user_id == current_user.id)
    
    if status:
        statement = statement.where(Ticket.status == status)
    
    statement = statement.offset(skip).limit(limit).order_by(Ticket.created_at.desc())
    
    tickets = session.exec(statement).all()
    
    # Count responses for each ticket
    tickets_public = []
    for ticket in tickets:
        response_count = len(ticket.responses) if ticket.responses else 0
        tickets_public.append(TicketPublic(**ticket.model_dump(), response_count=response_count))
    
    # Get total count
    count_statement = select(func.count()).select_from(Ticket).where(Ticket.user_id == current_user.id)
    if status:
        count_statement = count_statement.where(Ticket.status == status)
    count = session.exec(count_statement).one()
    
    return TicketsPublic(data=tickets_public, count=count)


@router.get("/all", response_model=TicketsPublic)
def get_all_tickets(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    priority: str | None = None
) -> Any:
    """Get all tickets (Admin only)."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    statement = select(Ticket)
    
    if status:
        statement = statement.where(Ticket.status == status)
    if priority:
        statement = statement.where(Ticket.priority == priority)
    
    statement = statement.offset(skip).limit(limit).order_by(Ticket.created_at.desc())
    
    tickets = session.exec(statement).all()
    
    tickets_public = []
    for ticket in tickets:
        response_count = len(ticket.responses) if ticket.responses else 0
        tickets_public.append(TicketPublic(**ticket.model_dump(), response_count=response_count))
    
    count_statement = select(func.count()).select_from(Ticket)
    if status:
        count_statement = count_statement.where(Ticket.status == status)
    if priority:
        count_statement = count_statement.where(Ticket.priority == priority)
    count = session.exec(count_statement).one()
    
    return TicketsPublic(data=tickets_public, count=count)


@router.get("/{ticket_id}", response_model=TicketPublic)
def get_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_id: uuid.UUID
) -> Any:
    """Get a specific ticket."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Check permissions
    if ticket.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    response_count = len(ticket.responses) if ticket.responses else 0
    return TicketPublic(**ticket.model_dump(), response_count=response_count)


@router.patch("/{ticket_id}", response_model=TicketPublic)
def update_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_id: uuid.UUID,
    ticket_update: TicketUpdate
) -> Any:
    """Update a ticket."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Only owner or admin can update
    if ticket.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    update_data = ticket_update.model_dump(exclude_unset=True)
    
    # Handle status changes
    if "status" in update_data:
        if update_data["status"] == "resolved" and not ticket.resolved_at:
            ticket.resolved_at = datetime.utcnow()
        elif update_data["status"] == "closed" and not ticket.closed_at:
            ticket.closed_at = datetime.utcnow()
    
    for key, value in update_data.items():
        setattr(ticket, key, value)
    
    ticket.updated_at = datetime.utcnow()
    
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    
    response_count = len(ticket.responses) if ticket.responses else 0
    return TicketPublic(**ticket.model_dump(), response_count=response_count)


@router.delete("/{ticket_id}", response_model=Message)
def delete_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_id: uuid.UUID
) -> Any:
    """Delete a ticket."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Only owner or admin can delete
    if ticket.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    session.delete(ticket)
    session.commit()
    
    return Message(message="Ticket deleted successfully")


# ==================== TICKET RESPONSES ====================

@router.post("/{ticket_id}/responses", response_model=TicketResponsePublic)
def create_ticket_response(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_id: uuid.UUID,
    response_in: TicketResponseCreate
) -> Any:
    """Add a response to a ticket."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Check permissions
    if ticket.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    response = TicketResponse(
        message=response_in.message,
        is_staff_response=response_in.is_staff_response if current_user.is_superuser else False,
        ticket_id=ticket_id,
        user_id=current_user.id,
        created_at=datetime.utcnow()
    )
    
    # Update ticket
    ticket.updated_at = datetime.utcnow()
    
    session.add(response)
    session.add(ticket)
    session.commit()
    session.refresh(response)
    
    return response


@router.get("/{ticket_id}/responses", response_model=TicketResponsesPublic)
def get_ticket_responses(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100
) -> Any:
    """Get all responses for a ticket."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Check permissions
    if ticket.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    statement = (
        select(TicketResponse)
        .where(TicketResponse.ticket_id == ticket_id)
        .offset(skip)
        .limit(limit)
        .order_by(TicketResponse.created_at.asc())
    )
    
    responses = session.exec(statement).all()
    
    count_statement = select(func.count()).select_from(TicketResponse).where(TicketResponse.ticket_id == ticket_id)
    count = session.exec(count_statement).one()
    
    return TicketResponsesPublic(data=responses, count=count)


@router.get("/stats/summary", response_model=dict)
def get_ticket_stats(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """Get ticket statistics."""
    if current_user.is_superuser:
        # Admin sees all tickets
        total = session.exec(select(func.count()).select_from(Ticket)).one()
        open_count = session.exec(select(func.count()).select_from(Ticket).where(Ticket.status == "open")).one()
        in_progress = session.exec(select(func.count()).select_from(Ticket).where(Ticket.status == "in_progress")).one()
        resolved = session.exec(select(func.count()).select_from(Ticket).where(Ticket.status == "resolved")).one()
        closed = session.exec(select(func.count()).select_from(Ticket).where(Ticket.status == "closed")).one()
    else:
        # User sees only their tickets
        total = session.exec(select(func.count()).select_from(Ticket).where(Ticket.user_id == current_user.id)).one()
        open_count = session.exec(select(func.count()).select_from(Ticket).where(Ticket.user_id == current_user.id, Ticket.status == "open")).one()
        in_progress = session.exec(select(func.count()).select_from(Ticket).where(Ticket.user_id == current_user.id, Ticket.status == "in_progress")).one()
        resolved = session.exec(select(func.count()).select_from(Ticket).where(Ticket.user_id == current_user.id, Ticket.status == "resolved")).one()
        closed = session.exec(select(func.count()).select_from(Ticket).where(Ticket.user_id == current_user.id, Ticket.status == "closed")).one()
    
    return {
        "total": total,
        "open": open_count,
        "in_progress": in_progress,
        "resolved": resolved,
        "closed": closed
    }