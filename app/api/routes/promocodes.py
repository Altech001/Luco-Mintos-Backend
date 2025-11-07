# type: ignore
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.models import PromoCode, User, Message

router = APIRouter(prefix="/promo-codes", tags=["promo-codes"])


# Pydantic models for requests/responses
class PromoCodeCreate(BaseModel):
    code: str = Field(..., max_length=50, description="Unique promo code")
    sms_cost: str = Field(..., max_length=50, description="Special SMS cost (e.g., '25', '18')")
    is_active: bool = Field(default=True)
    expires_at: datetime | None = Field(default=None, description="Expiration date")
    max_uses: int | None = Field(default=None, description="Maximum number of uses")
    description: str | None = Field(default=None, max_length=255, description="Description of the promo")


class PromoCodeUpdate(BaseModel):
    sms_cost: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    expires_at: datetime | None = None
    max_uses: int | None = None
    description: str | None = None


class PromoCodePublic(BaseModel):
    id: uuid.UUID
    code: str
    sms_cost: str
    is_active: bool
    expires_at: datetime | None
    max_uses: int | None
    current_uses: int
    description: str | None
    created_at: datetime


class PromoCodesPublic(BaseModel):
    data: list[PromoCodePublic]
    count: int


class ApplyPromoCodeRequest(BaseModel):
    code: str = Field(..., description="Promo code to apply")


class ApplyPromoCodeResponse(BaseModel):
    code: str
    old_sms_cost: str
    new_sms_cost: str
    savings_per_sms: float
    success: bool
    message: str


@router.post("/", response_model=PromoCodePublic)
def create_promo_code(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    promo_data: PromoCodeCreate
) -> Any:
    """
    Create a new promo code with special SMS pricing. (Admin only)
    """
    # TODO: Add admin permission check
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # Check if code already exists
    statement = select(PromoCode).where(PromoCode.code == promo_data.code)
    existing = session.exec(statement).first()
    if existing:
        raise HTTPException(status_code=400, detail="Promo code already exists")
    
    promo_code = PromoCode(
        code=promo_data.code.upper(),  # Store as uppercase
        sms_cost=promo_data.sms_cost,
        is_active=promo_data.is_active,
        expires_at=promo_data.expires_at,
        max_uses=promo_data.max_uses,
        current_uses=0,
        description=promo_data.description,
        created_at=datetime.utcnow()
    )
    
    session.add(promo_code)
    session.commit()
    session.refresh(promo_code)
    
    return promo_code


@router.get("/", response_model=PromoCodesPublic)
def get_all_promo_codes(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False
) -> Any:
    """
    Get all promo codes. (Admin only)
    """
    # TODO: Add admin permission check
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    statement = select(PromoCode)
    if active_only:
        statement = statement.where(PromoCode.is_active == True)
    
    statement = statement.offset(skip).limit(limit)
    
    promo_codes = session.exec(statement).all()
    count_statement = select(PromoCode)
    if active_only:
        count_statement = count_statement.where(PromoCode.is_active == True)
    
    count = len(session.exec(count_statement).all())
    
    return PromoCodesPublic(data=promo_codes, count=count)


@router.get("/{code}", response_model=PromoCodePublic)
def get_promo_code(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    code: str
) -> Any:
    """
    Get a specific promo code by code. (Admin only)
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    statement = select(PromoCode).where(PromoCode.code == code.upper())
    promo_code = session.exec(statement).first()
    
    if not promo_code:
        raise HTTPException(status_code=404, detail="Promo code not found")
    
    return promo_code


@router.patch("/{promo_id}", response_model=PromoCodePublic)
def update_promo_code(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    promo_id: uuid.UUID,
    promo_update: PromoCodeUpdate
) -> Any:
    """
    Update a promo code. (Admin only)
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    promo_code = session.get(PromoCode, promo_id)
    if not promo_code:
        raise HTTPException(status_code=404, detail="Promo code not found")
    
    update_data = promo_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(promo_code, key, value)
    
    session.add(promo_code)
    session.commit()
    session.refresh(promo_code)
    
    return promo_code


@router.delete("/{promo_id}", response_model=Message)
def delete_promo_code(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    promo_id: uuid.UUID
) -> Any:
    """
    Delete a promo code. (Admin only)
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    promo_code = session.get(PromoCode, promo_id)
    if not promo_code:
        raise HTTPException(status_code=404, detail="Promo code not found")
    
    session.delete(promo_code)
    session.commit()
    
    return Message(message="Promo code deleted successfully")


@router.post("/validate", response_model=dict)
def validate_promo_code(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    code: str
) -> Any:
    """
    Validate a promo code without applying it.
    Anyone can validate to see if code is valid.
    """
    statement = select(PromoCode).where(PromoCode.code == code.upper())
    promo_code = session.exec(statement).first()
    
    if not promo_code:
        return {
            "valid": False,
            "message": "Promo code not found",
            "code": code
        }
    
    if not promo_code.is_active:
        return {
            "valid": False,
            "message": "Promo code is inactive",
            "code": code
        }
    
    if promo_code.expires_at and promo_code.expires_at < datetime.utcnow():
        return {
            "valid": False,
            "message": "Promo code has expired",
            "code": code,
            "expired_at": promo_code.expires_at
        }
    
    if promo_code.max_uses and promo_code.current_uses >= promo_code.max_uses:
        return {
            "valid": False,
            "message": "Promo code usage limit reached",
            "code": code
        }
    
    # Calculate potential savings
    current_sms_cost = float(current_user.sms_cost or "32")
    new_sms_cost = float(promo_code.sms_cost)
    savings_per_sms = current_sms_cost - new_sms_cost
    
    return {
        "valid": True,
        "message": "Promo code is valid",
        "code": promo_code.code,
        "new_sms_cost": promo_code.sms_cost,
        "current_sms_cost": current_user.sms_cost,
        "savings_per_sms": savings_per_sms,
        "description": promo_code.description
    }


@router.post("/apply", response_model=ApplyPromoCodeResponse)
def apply_promo_code(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    request: ApplyPromoCodeRequest
) -> Any:
    """
    Apply a promo code to get special SMS pricing.
    This updates the user's sms_cost permanently (or until another promo is applied).
    """
    statement = select(PromoCode).where(PromoCode.code == request.code.upper())
    promo_code = session.exec(statement).first()
    
    if not promo_code:
        raise HTTPException(status_code=404, detail="Promo code not found")
    
    # Validate promo code
    if not promo_code.is_active:
        raise HTTPException(status_code=400, detail="Promo code is inactive")
    
    if promo_code.expires_at and promo_code.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Promo code has expired")
    
    if promo_code.max_uses and promo_code.current_uses >= promo_code.max_uses:
        raise HTTPException(status_code=400, detail="Promo code usage limit reached")
    
    # Get user from database
    user = session.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Store old SMS cost for response
    old_sms_cost = user.sms_cost or "32"
    new_sms_cost = promo_code.sms_cost
    
    # Check if new rate is actually better
    if float(new_sms_cost) >= float(old_sms_cost):
        raise HTTPException(
            status_code=400, 
            detail=f"Promo code SMS cost ({new_sms_cost}) is not better than your current rate ({old_sms_cost})"
        )
    
    # Update user's SMS cost
    user.sms_cost = new_sms_cost
    
    # Increment promo code usage count
    promo_code.current_uses += 1
    
    session.add(user)
    session.add(promo_code)
    session.commit()
    session.refresh(user)
    
    savings_per_sms = float(old_sms_cost) - float(new_sms_cost)
    
    return ApplyPromoCodeResponse(
        code=promo_code.code,
        old_sms_cost=old_sms_cost,
        new_sms_cost=new_sms_cost,
        savings_per_sms=savings_per_sms,
        success=True,
        message=f"Promo code applied! Your SMS cost is now {new_sms_cost} UGX (was {old_sms_cost} UGX)"
    )


@router.get("/{promo_id}/stats", response_model=dict)
def get_promo_code_stats(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    promo_id: uuid.UUID
) -> Any:
    """
    Get usage statistics for a promo code. (Admin only)
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    promo_code = session.get(PromoCode, promo_id)
    if not promo_code:
        raise HTTPException(status_code=404, detail="Promo code not found")
    
    usage_percentage = 0
    if promo_code.max_uses:
        usage_percentage = (promo_code.current_uses / promo_code.max_uses) * 100
    
    is_expired = promo_code.expires_at and promo_code.expires_at < datetime.utcnow()
    is_maxed_out = promo_code.max_uses and promo_code.current_uses >= promo_code.max_uses
    
    # Count how many users are currently using this SMS rate
    statement = select(User).where(User.sms_cost == promo_code.sms_cost)
    users_with_rate = session.exec(statement).all()
    
    return {
        "code": promo_code.code,
        "sms_cost": promo_code.sms_cost,
        "current_uses": promo_code.current_uses,
        "max_uses": promo_code.max_uses,
        "usage_percentage": round(usage_percentage, 2) if promo_code.max_uses else None,
        "users_with_this_rate": len(users_with_rate),
        "is_active": promo_code.is_active,
        "is_expired": is_expired,
        "is_maxed_out": is_maxed_out,
        "expires_at": promo_code.expires_at,
        "description": promo_code.description,
        "created_at": promo_code.created_at
    }


@router.get("/my/active", response_model=dict)
def get_my_active_promo(
    current_user: CurrentUser
) -> Any:
    """
    Check if current user has a special promo rate applied.
    """
    # Check if user's SMS cost matches any standard plan
    standard_costs = ["32", "28", "24", "20"]  # From PLANS in user-data router
    
    has_promo = current_user.sms_cost not in standard_costs
    
    return {
        "user_id": current_user.id,
        "current_sms_cost": current_user.sms_cost,
        "has_special_rate": has_promo,
        "message": "You have a special promotional rate!" if has_promo else "You are on a standard plan rate"
    }