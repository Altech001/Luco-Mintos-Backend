from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, EmailStr
from sqlmodel import select, func, and_, or_, desc, asc
from sqlalchemy import case
from sqlalchemy.orm import selectinload, joinedload
from typing import Optional, List
from datetime import datetime, timedelta
import uuid

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.models import (
    Message,
    User,
    UserPublic,
    Transaction,
    TransactionPublic,
    SmsHistory,
    SmsHistoryPublic,
    Template,
    TemplatePublic,
    Ticket,
    TicketPublic,
    TicketResponse,
    ApiKey,
    ApiKeyPublic,
    Contact,
    ContactGroup,
)
from app.core.config import settings
from app.core.security import get_password_hash, verify_password

router = APIRouter(prefix="/admin", tags=["More Admin Privileges"])


# ==================== PLAN CONFIGURATION ====================

# Pricing plans configuration (same as in userdata.py)
PLANS = {
    "Basic": {
        "sms_cost": "35",
        "description": "Basic plan with standard SMS rates",
        "features": ["Standard SMS delivery", "Basic templates", "Email support", "API access"]
    },
    "Standard": {
        "sms_cost": "33",
        "description": "Standard plan with reduced SMS rates",
        "features": ["Priority SMS delivery", "Unlimited templates", "Email support", "API access"]
    },
    "Premium": {
        "sms_cost": "32",
        "description": "Premium plan with best SMS rates",
        "features": ["Priority SMS delivery", "Unlimited templates", "24/7 Phone support", "API access", "Advanced analytics"]
    },
    "Enterprise": {
        "sms_cost": "30",
        "description": "Enterprise plan with lowest SMS rates",
        "features": ["Dedicated SMS delivery", "Unlimited everything", "24/7 Priority support", "API access", "Advanced analytics", "Custom integrations"]
    }
}


# ==================== RESPONSE MODELS ====================

class UserDetailedInfo(BaseModel):
    """Comprehensive user information with aggregated data"""
    user: UserPublic
    total_transactions: int
    total_transaction_amount: float
    total_sms_sent: int
    total_sms_cost: float
    total_templates: int
    total_contacts: int
    total_tickets: int
    open_tickets: int
    recent_activity: str
    account_age_days: int
    last_transaction_date: Optional[datetime]
    last_sms_date: Optional[datetime]


class UserSearchResult(BaseModel):
    """User search result with key metrics"""
    id: uuid.UUID
    email: str
    full_name: Optional[str]
    is_active: bool
    plan_sub: Optional[str]
    wallet: Optional[str]
    total_sms_sent: int
    total_transactions: int
    created_at: Optional[datetime] = None


class AddBalanceRequest(BaseModel):
    """Request model for adding balance to user account"""
    user_id: uuid.UUID
    amount: float
    description: Optional[str] = "Admin credit adjustment"
    payment_method: str = "admin_adjustment"


class BulkTemplateCreate(BaseModel):
    """Request model for creating prebuilt templates"""
    name: str
    content: str
    tag: str = "prebuilt"
    default: bool = True


class SystemStats(BaseModel):
    """System-wide statistics"""
    total_users: int
    active_users: int
    total_transactions: float
    total_sms_sent: int
    total_revenue: float
    users_by_plan: dict
    recent_signups: int


class UserActivityLog(BaseModel):
    """User activity log entry"""
    user_id: uuid.UUID
    activity_type: str
    timestamp: datetime
    details: str
    ip_address: Optional[str] = None


# ==================== BACKGROUND TASKS ====================

async def log_admin_action(
    admin_id: uuid.UUID,
    action: str,
    target_user_id: Optional[uuid.UUID] = None,
    details: Optional[str] = None
):
    """Background task to log admin actions for audit trail"""
    # This would typically write to a separate admin_logs table
    # For now, we'll just print (you can extend this to write to DB)
    print(f"[ADMIN LOG] Admin {admin_id} performed {action} on user {target_user_id}: {details}")


async def recalculate_user_metrics(session: SessionDep, user_id: uuid.UUID):
    """Background task to recalculate user metrics after balance changes"""
    user = session.get(User, user_id)
    if user:
        # Recalculate wallet balance based on transactions
        statement = select(func.sum(Transaction.amount)).where(
            Transaction.user_id == user_id,
            Transaction.status == "completed"
        )
        total = session.exec(statement).first() or 0.0
        print(f"[METRICS] User {user_id} total completed transactions: {total}")




# ==================== USER SEARCH & DETAILED INFO ====================

@router.get("/users/search", response_model=List[UserSearchResult])
async def search_users(
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
    query: Optional[str] = Query(None, description="Search by email, name, or ID"),
    plan: Optional[str] = Query(None, description="Filter by plan subscription"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
) -> List[UserSearchResult]:
    """
    Search users with optimized query using indexing.
    Supports filtering by email, name, plan, and active status.
    Uses database indexes on email and user_id for fast lookups.
    """
    # Build base query with joins for aggregated data
    statement = select(
        User,
        func.count(SmsHistory.id).label("total_sms"),
        func.count(Transaction.id).label("total_transactions")
    ).outerjoin(
        SmsHistory, SmsHistory.user_id == User.id
    ).outerjoin(
        Transaction, Transaction.user_id == User.id
    ).group_by(User.id)
    
    # Apply filters with indexed columns for optimization
    filters = []
    if query:
        # Search across indexed email field and full_name
        filters.append(
            or_(
                User.email.ilike(f"%{query}%"),
                User.full_name.ilike(f"%{query}%") if query else False
            )
        )
    
    if plan:
        filters.append(User.plan_sub == plan)
    
    if is_active is not None:
        filters.append(User.is_active == is_active)
    
    if filters:
        statement = statement.where(and_(*filters))
    
    # Apply pagination
    statement = statement.offset(skip).limit(limit)
    
    # Execute query
    results = session.exec(statement).all()
    
    # Format response
    search_results = []
    for user, sms_count, transaction_count in results:
        search_results.append(UserSearchResult(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            plan_sub=user.plan_sub,
            wallet=user.wallet,
            total_sms_sent=sms_count or 0,
            total_transactions=transaction_count or 0
        ))
    
    return search_results


@router.get("/users/{user_id}/detailed", response_model=UserDetailedInfo)
async def get_user_detailed_info(
    user_id: uuid.UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
) -> UserDetailedInfo:
    """
    Get comprehensive user information with all related data.
    Uses optimized joins and aggregations for performance.
    Indexes on user_id foreign keys ensure fast lookups.
    """
    # Get user with eager loading of relationships
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Aggregate transaction data with indexed query
    transaction_stats = session.exec(
        select(
            func.count(Transaction.id).label("count"),
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            func.max(Transaction.created_at).label("last_date")
        ).where(Transaction.user_id == user_id)
    ).first()
    
    # Aggregate SMS data with indexed query on user_id
    sms_stats = session.exec(
        select(
            func.count(SmsHistory.id).label("count"),
            func.coalesce(func.sum(SmsHistory.cost), 0).label("total_cost"),
            func.max(SmsHistory.created_at).label("last_date")
        ).where(SmsHistory.user_id == user_id)
    ).first()
    
    # Count templates
    template_count = session.exec(
        select(func.count(Template.id)).where(Template.owner_id == user_id)
    ).first() or 0
    
    # Count contacts
    contact_count = session.exec(
        select(func.count(Contact.id)).where(Contact.user_id == user_id)
    ).first() or 0
    
    # Count tickets with status filter
    ticket_stats = session.exec(
        select(
            func.count(Ticket.id).label("total"),
            func.sum(case((Ticket.status == "open", 1), else_=0)).label("open_count")
        ).where(Ticket.user_id == user_id)
    ).first()
    
    # Calculate account age
    # Assuming user has a created_at field or using current time as placeholder
    account_age = 0  # You may need to add created_at to User model
    
    # Determine recent activity
    recent_activity = "No recent activity"
    if sms_stats and sms_stats[2]:
        days_since_sms = (datetime.utcnow() - sms_stats[2]).days
        if days_since_sms < 7:
            recent_activity = f"Sent SMS {days_since_sms} days ago"
    
    return UserDetailedInfo(
        user=UserPublic.model_validate(user),
        total_transactions=transaction_stats[0] if transaction_stats else 0,
        total_transaction_amount=float(transaction_stats[1]) if transaction_stats else 0.0,
        total_sms_sent=sms_stats[0] if sms_stats else 0,
        total_sms_cost=float(sms_stats[1]) if sms_stats else 0.0,
        total_templates=template_count,
        total_contacts=contact_count,
        total_tickets=ticket_stats[0] if ticket_stats else 0,
        open_tickets=int(ticket_stats[1]) if ticket_stats and ticket_stats[1] else 0,
        recent_activity=recent_activity,
        account_age_days=account_age,
        last_transaction_date=transaction_stats[2] if transaction_stats else None,
        last_sms_date=sms_stats[2] if sms_stats else None
    )


# ==================== USER BALANCE MANAGEMENT ====================

@router.post("/users/{user_id}/add-balance", response_model=TransactionPublic)
async def add_balance_to_user(
    user_id: uuid.UUID,
    request: AddBalanceRequest,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_superuser),
) -> TransactionPublic:
    """
    Add balance to user account with transaction tracking.
    Uses indexed user_id for fast lookup and creates audit trail.
    Background task recalculates user metrics for consistency.
    """
    # Verify user exists using indexed primary key lookup
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get current balance
    current_balance = float(user.wallet or "0.0")
    new_balance = current_balance + request.amount
    
    # Create transaction record
    transaction = Transaction(
        user_id=user_id,
        transaction_type="credit",
        amount=request.amount,
        currency="UGX",
        description=request.description,
        status="completed",
        payment_method=request.payment_method,
        reference_number=f"ADMIN-{uuid.uuid4().hex[:8].upper()}",
        balance_before=current_balance,
        balance_after=new_balance,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    # Update user wallet
    user.wallet = str(new_balance)
    
    # Commit changes
    session.add(transaction)
    session.add(user)
    session.commit()
    session.refresh(transaction)
    
    # Schedule background tasks
    background_tasks.add_task(
        log_admin_action,
        admin_id=current_user.id,
        action="add_balance",
        target_user_id=user_id,
        details=f"Added {request.amount} UGX. New balance: {new_balance}"
    )
    background_tasks.add_task(recalculate_user_metrics, session, user_id)
    
    return TransactionPublic.model_validate(transaction)


# ==================== PREBUILT TEMPLATES ====================

@router.post("/templates/prebuilt", response_model=TemplatePublic)
async def create_prebuilt_template(
    template_data: BulkTemplateCreate,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_superuser),
) -> TemplatePublic:
    """
    Create prebuilt templates that are displayed to all users.
    These templates have default=True and are owned by admin.
    Uses indexed owner_id for efficient template queries.
    """
    # Create template owned by admin
    template = Template(
        name=template_data.name,
        content=template_data.content,
        tag=template_data.tag,
        default=template_data.default,
        owner_id=current_user.id,
        created_at=datetime.utcnow()
    )
    
    session.add(template)
    session.commit()
    session.refresh(template)
    
    # Log action
    background_tasks.add_task(
        log_admin_action,
        admin_id=current_user.id,
        action="create_prebuilt_template",
        details=f"Created template: {template_data.name}"
    )
    
    return TemplatePublic.model_validate(template)


@router.get("/templates/prebuilt", response_model=List[TemplatePublic])
async def list_prebuilt_templates(
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
) -> List[TemplatePublic]:
    """
    List all prebuilt templates.
    Uses indexed query on default flag for optimization.
    """
    statement = (
        select(Template)
        .where(Template.default == True)
        .order_by(desc(Template.created_at))
        .offset(skip)
        .limit(limit)
    )
    
    templates = session.exec(statement).all()
    return [TemplatePublic.model_validate(t) for t in templates]


# ==================== USER ACTIVITY LOGS ====================

@router.get("/users/{user_id}/activity-logs", response_model=List[UserActivityLog])
async def get_user_activity_logs(
    user_id: uuid.UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
    activity_type: Optional[str] = Query(None, description="Filter by activity type"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
) -> List[UserActivityLog]:
    """
    Get user activity logs from multiple sources.
    Aggregates data from transactions, SMS history, and tickets.
    Uses indexed created_at fields for efficient time-based queries.
    """
    # Verify user exists
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    activity_logs = []
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Get transaction activities (indexed on created_at and user_id)
    if not activity_type or activity_type == "transaction":
        transactions = session.exec(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.created_at >= cutoff_date
            )
            .order_by(desc(Transaction.created_at))
            .limit(limit)
        ).all()
        
        for txn in transactions:
            activity_logs.append(UserActivityLog(
                user_id=user_id,
                activity_type="transaction",
                timestamp=txn.created_at,
                details=f"{txn.transaction_type.upper()}: {txn.amount} {txn.currency} - {txn.description}"
            ))
    
    # Get SMS activities (indexed on created_at and user_id)
    if not activity_type or activity_type == "sms":
        sms_records = session.exec(
            select(SmsHistory)
            .where(
                SmsHistory.user_id == user_id,
                SmsHistory.created_at >= cutoff_date
            )
            .order_by(desc(SmsHistory.created_at))
            .limit(limit)
        ).all()
        
        for sms in sms_records:
            activity_logs.append(UserActivityLog(
                user_id=user_id,
                activity_type="sms",
                timestamp=sms.created_at,
                details=f"SMS to {sms.recipient}: {sms.status} - Cost: {sms.cost}"
            ))
    
    # Get ticket activities (indexed on created_at and user_id)
    if not activity_type or activity_type == "ticket":
        tickets = session.exec(
            select(Ticket)
            .where(
                Ticket.user_id == user_id,
                Ticket.created_at >= cutoff_date
            )
            .order_by(desc(Ticket.created_at))
            .limit(limit)
        ).all()
        
        for ticket in tickets:
            activity_logs.append(UserActivityLog(
                user_id=user_id,
                activity_type="ticket",
                timestamp=ticket.created_at,
                details=f"Ticket: {ticket.subject} - Status: {ticket.status} - Priority: {ticket.priority}"
            ))
    
    # Sort all activities by timestamp
    activity_logs.sort(key=lambda x: x.timestamp, reverse=True)
    
    # Apply pagination
    return activity_logs[skip:skip + limit]


# ==================== SYSTEM STATISTICS ====================

@router.get("/system/stats", response_model=SystemStats)
async def get_system_statistics(
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
) -> SystemStats:
    """
    Get system-wide statistics with optimized aggregation queries.
    Uses database-level aggregations for performance.
    All queries use indexed fields for fast execution.
    """
    # Total and active users
    total_users = session.exec(select(func.count(User.id))).first() or 0
    active_users = session.exec(
        select(func.count(User.id)).where(User.is_active == True)
    ).first() or 0
    
    # Total transaction volume
    total_transaction_amount = session.exec(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.status == "completed")
    ).first() or 0.0
    
    # Total SMS sent
    total_sms = session.exec(select(func.count(SmsHistory.id))).first() or 0
    
    # Total revenue (completed transactions of type 'payment')
    total_revenue = session.exec(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.status == "completed",
            Transaction.transaction_type == "payment"
        )
    ).first() or 0.0
    
    # Users by plan (grouped aggregation)
    plan_stats = session.exec(
        select(User.plan_sub, func.count(User.id))
        .group_by(User.plan_sub)
    ).all()
    users_by_plan = {plan: count for plan, count in plan_stats}
    
    # Recent signups (last 7 days) - would need created_at field
    # For now, returning 0 as placeholder
    recent_signups = 0
    
    return SystemStats(
        total_users=total_users,
        active_users=active_users,
        total_transactions=float(total_transaction_amount),
        total_sms_sent=total_sms,
        total_revenue=float(total_revenue),
        users_by_plan=users_by_plan,
        recent_signups=recent_signups
    )


# ==================== BULK OPERATIONS ====================

@router.post("/users/bulk-update-plan")
async def bulk_update_user_plan(
    user_ids: List[uuid.UUID],
    new_plan: str,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_superuser),
) -> Message:
    """
    Bulk update user plans with optimized batch query.
    Uses indexed user_id for efficient updates.
    Automatically updates SMS cost based on the new plan.
    """
    if len(user_ids) > 1000:
        raise HTTPException(
            status_code=400,
            detail="Cannot update more than 1000 users at once"
        )
    
    # Validate plan exists
    if new_plan not in PLANS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan. Available plans: {', '.join(PLANS.keys())}"
        )
    
    # Get the SMS cost for the new plan
    new_sms_cost = PLANS[new_plan]["sms_cost"]
    
    # Bulk update using indexed primary keys
    statement = select(User).where(User.id.in_(user_ids))
    users = session.exec(statement).all()
    
    updated_count = 0
    for user in users:
        user.plan_sub = new_plan
        user.sms_cost = new_sms_cost  # Update SMS cost to match the plan
        session.add(user)
        updated_count += 1
    
    session.commit()
    
    # Log action
    background_tasks.add_task(
        log_admin_action,
        admin_id=current_user.id,
        action="bulk_update_plan",
        details=f"Updated {updated_count} users to plan: {new_plan} (SMS cost: {new_sms_cost})"
    )
    
    return Message(message=f"Successfully updated {updated_count} users to plan: {new_plan} with SMS cost: {new_sms_cost}")


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: uuid.UUID,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_superuser),
) -> Message:
    """
    Deactivate a user account.
    Uses indexed primary key lookup.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_active = False
    session.add(user)
    session.commit()
    
    # Log action
    background_tasks.add_task(
        log_admin_action,
        admin_id=current_user.id,
        action="deactivate_user",
        target_user_id=user_id,
        details=f"Deactivated user: {user.email}"
    )
    
    return Message(message=f"User {user.email} has been deactivated")


@router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: uuid.UUID,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_superuser),
) -> Message:
    """
    Activate a user account.
    Uses indexed primary key lookup.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_active = True
    session.add(user)
    session.commit()
    
    # Log action
    background_tasks.add_task(
        log_admin_action,
        admin_id=current_user.id,
        action="activate_user",
        target_user_id=user_id,
        details=f"Activated user: {user.email}"
    )
    
    return Message(message=f"User {user.email} has been activated")


# ==================== USER TICKETS MANAGEMENT ====================

@router.get("/users/{user_id}/tickets", response_model=List[TicketPublic])
async def get_user_tickets(
    user_id: uuid.UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
    status: Optional[str] = Query(None, description="Filter by ticket status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=200),
) -> List[TicketPublic]:
    """
    Get all tickets for a specific user with filtering.
    Uses indexed user_id and created_at for efficient queries.
    Supports filtering by status and priority.
    """
    # Verify user exists
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Build query with indexed fields
    statement = select(Ticket).where(Ticket.user_id == user_id)
    
    # Apply filters
    if status:
        statement = statement.where(Ticket.status == status)
    if priority:
        statement = statement.where(Ticket.priority == priority)
    
    # Order by created_at (indexed) and apply pagination
    statement = statement.order_by(desc(Ticket.created_at)).offset(skip).limit(limit)
    
    tickets = session.exec(statement).all()
    
    # Add response count to each ticket
    result = []
    for ticket in tickets:
        ticket_public = TicketPublic.model_validate(ticket)
        # Count responses for this ticket
        response_count = session.exec(
            select(func.count()).where(
                TicketResponse.ticket_id == ticket.id
            )
        ).first() or 0
        ticket_public.response_count = response_count
        result.append(ticket_public)
    
    return result


@router.get("/tickets/all", response_model=List[TicketPublic])
async def get_all_tickets(
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    assigned_to_me: bool = Query(False, description="Show only tickets assigned to me"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
) -> List[TicketPublic]:
    """
    Get all tickets in the system with advanced filtering.
    Optimized with indexed queries on status, priority, and created_at.
    """
    statement = select(Ticket)
    
    # Apply filters
    filters = []
    if status:
        filters.append(Ticket.status == status)
    if priority:
        filters.append(Ticket.priority == priority)
    if assigned_to_me:
        filters.append(Ticket.assigned_to == current_user.id)
    
    if filters:
        statement = statement.where(and_(*filters))
    
    # Order by priority and created_at
    statement = (
        statement
        .order_by(
            case(
                (Ticket.priority == "urgent", 1),
                (Ticket.priority == "high", 2),
                (Ticket.priority == "medium", 3),
                (Ticket.priority == "low", 4),
                else_=5
            ),
            desc(Ticket.created_at)
        )
        .offset(skip)
        .limit(limit)
    )
    
    tickets = session.exec(statement).all()
    
    # Add response count
    result = []
    for ticket in tickets:
        ticket_public = TicketPublic.model_validate(ticket)
        response_count = session.exec(
            select(func.count()).where(
                TicketResponse.ticket_id == ticket.id
            )
        ).first() or 0
        ticket_public.response_count = response_count
        result.append(ticket_public)
    
    return result


@router.patch("/tickets/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: uuid.UUID,
    assigned_to: uuid.UUID,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_superuser),
) -> TicketPublic:
    """
    Assign a ticket to a support agent.
    Uses indexed primary key lookups.
    """
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Verify assigned user exists
    assigned_user = session.get(User, assigned_to)
    if not assigned_user:
        raise HTTPException(status_code=404, detail="Assigned user not found")
    
    ticket.assigned_to = assigned_to
    ticket.updated_at = datetime.utcnow()
    
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    
    # Log action
    background_tasks.add_task(
        log_admin_action,
        admin_id=current_user.id,
        action="assign_ticket",
        details=f"Assigned ticket {ticket_id} to {assigned_user.email}"
    )
    
    return TicketPublic.model_validate(ticket)


# ==================== API KEYS MANAGEMENT ====================

@router.get("/users/{user_id}/api-keys", response_model=List[ApiKeyPublic])
async def get_user_api_keys(
    user_id: uuid.UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
) -> List[ApiKeyPublic]:
    """
    Get all API keys for a specific user.
    Uses indexed user_id for efficient lookup.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    statement = select(ApiKey).where(ApiKey.user_id == user_id)
    
    if is_active is not None:
        statement = statement.where(ApiKey.is_active == is_active)
    
    statement = statement.order_by(desc(ApiKey.created_at))
    
    api_keys = session.exec(statement).all()
    return [ApiKeyPublic.model_validate(key) for key in api_keys]


@router.post("/users/{user_id}/api-keys/{key_id}/revoke")
async def revoke_api_key(
    user_id: uuid.UUID,
    key_id: uuid.UUID,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_superuser),
) -> Message:
    """
    Revoke a user's API key.
    Uses indexed primary key lookup.
    """
    api_key = session.get(ApiKey, key_id)
    if not api_key or api_key.user_id != user_id:
        raise HTTPException(status_code=404, detail="API key not found")
    
    api_key.is_active = False
    session.add(api_key)
    session.commit()
    
    # Log action
    background_tasks.add_task(
        log_admin_action,
        admin_id=current_user.id,
        action="revoke_api_key",
        target_user_id=user_id,
        details=f"Revoked API key {api_key.prefix}"
    )
    
    return Message(message=f"API key {api_key.prefix} has been revoked")


# ==================== SMS ANALYTICS ====================

@router.get("/analytics/sms-overview")
async def get_sms_analytics(
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
) -> dict:
    """
    Get SMS analytics and statistics.
    Uses aggregated queries with indexed fields for performance.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Total SMS sent in period
    total_sms = session.exec(
        select(func.count(SmsHistory.id))
        .where(SmsHistory.created_at >= cutoff_date)
    ).first() or 0
    
    # Total cost
    total_cost = session.exec(
        select(func.coalesce(func.sum(SmsHistory.cost), 0))
        .where(SmsHistory.created_at >= cutoff_date)
    ).first() or 0.0
    
    # Success rate
    successful_sms = session.exec(
        select(func.count(SmsHistory.id))
        .where(
            SmsHistory.created_at >= cutoff_date,
            SmsHistory.status.in_(["sent", "delivered"])
        )
    ).first() or 0
    
    success_rate = (successful_sms / total_sms * 100) if total_sms > 0 else 0
    
    # Top users by SMS volume
    top_users = session.exec(
        select(
            User.id,
            User.email,
            User.full_name,
            func.count(SmsHistory.id).label("sms_count"),
            func.sum(SmsHistory.cost).label("total_cost")
        )
        .join(SmsHistory, SmsHistory.user_id == User.id)
        .where(SmsHistory.created_at >= cutoff_date)
        .group_by(User.id, User.email, User.full_name)
        .order_by(desc("sms_count"))
        .limit(10)
    ).all()
    
    # Status breakdown
    status_breakdown = session.exec(
        select(
            SmsHistory.status,
            func.count(SmsHistory.id).label("count")
        )
        .where(SmsHistory.created_at >= cutoff_date)
        .group_by(SmsHistory.status)
    ).all()
    
    return {
        "period_days": days,
        "total_sms_sent": total_sms,
        "total_cost": float(total_cost),
        "success_rate": round(success_rate, 2),
        "successful_sms": successful_sms,
        "failed_sms": total_sms - successful_sms,
        "top_users": [
            {
                "user_id": str(user_id),
                "email": email,
                "full_name": full_name,
                "sms_count": sms_count,
                "total_cost": float(total_cost or 0)
            }
            for user_id, email, full_name, sms_count, total_cost in top_users
        ],
        "status_breakdown": {
            status: count for status, count in status_breakdown
        }
    }


# ==================== TRANSACTION ANALYTICS ====================

@router.get("/analytics/transactions")
async def get_transaction_analytics(
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
) -> dict:
    """
    Get transaction analytics and revenue statistics.
    Uses optimized aggregation queries with indexed fields.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Total transactions
    total_transactions = session.exec(
        select(func.count(Transaction.id))
        .where(Transaction.created_at >= cutoff_date)
    ).first() or 0
    
    # Total revenue (completed payments)
    total_revenue = session.exec(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.created_at >= cutoff_date,
            Transaction.status == "completed",
            Transaction.transaction_type == "payment"
        )
    ).first() or 0.0
    
    # Total credits issued
    total_credits = session.exec(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.created_at >= cutoff_date,
            Transaction.transaction_type == "credit",
            Transaction.status == "completed"
        )
    ).first() or 0.0
    
    # Transaction type breakdown
    type_breakdown = session.exec(
        select(
            Transaction.transaction_type,
            func.count(Transaction.id).label("count"),
            func.sum(Transaction.amount).label("total_amount")
        )
        .where(
            Transaction.created_at >= cutoff_date,
            Transaction.status == "completed"
        )
        .group_by(Transaction.transaction_type)
    ).all()
    
    # Payment method breakdown
    payment_breakdown = session.exec(
        select(
            Transaction.payment_method,
            func.count(Transaction.id).label("count"),
            func.sum(Transaction.amount).label("total_amount")
        )
        .where(
            Transaction.created_at >= cutoff_date,
            Transaction.status == "completed"
        )
        .group_by(Transaction.payment_method)
    ).all()
    
    return {
        "period_days": days,
        "total_transactions": total_transactions,
        "total_revenue": float(total_revenue),
        "total_credits_issued": float(total_credits),
        "net_revenue": float(total_revenue - total_credits),
        "transaction_types": {
            txn_type: {
                "count": count,
                "total_amount": float(total_amount or 0)
            }
            for txn_type, count, total_amount in type_breakdown
        },
        "payment_methods": {
            method: {
                "count": count,
                "total_amount": float(total_amount or 0)
            }
            for method, count, total_amount in payment_breakdown if method
        }
    }


# ==================== USER ENGAGEMENT METRICS ====================

@router.get("/analytics/user-engagement")
async def get_user_engagement_metrics(
    session: SessionDep,
    current_user: User = Depends(get_current_active_superuser),
) -> dict:
    """
    Get user engagement metrics.
    Uses optimized queries with indexed fields.
    """
    # Active users (sent SMS in last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    active_users = session.exec(
        select(func.count(func.distinct(SmsHistory.user_id)))
        .where(SmsHistory.created_at >= thirty_days_ago)
    ).first() or 0
    
    # Users with API keys
    users_with_api_keys = session.exec(
        select(func.count(func.distinct(ApiKey.user_id)))
        .where(ApiKey.is_active == True)
    ).first() or 0
    
    # Users with templates
    users_with_templates = session.exec(
        select(func.count(func.distinct(Template.owner_id)))
    ).first() or 0
    
    # Average SMS per active user
    avg_sms_per_user = session.exec(
        select(func.avg(func.count(SmsHistory.id)))
        .where(SmsHistory.created_at >= thirty_days_ago)
        .group_by(SmsHistory.user_id)
    ).first() or 0
    
    return {
        "active_users_last_30_days": active_users,
        "users_with_active_api_keys": users_with_api_keys,
        "users_with_templates": users_with_templates,
        "avg_sms_per_active_user": round(float(avg_sms_per_user or 0), 2),
        "total_users": session.exec(select(func.count(User.id))).first() or 0
    }
