# type: ignore 
import uuid
from typing import Any
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import Transaction, User, Message

router = APIRouter(prefix="/user-data", tags=["user-data"])


# Pricing plans configuration
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


# Pydantic models for requests/responses
class PlanInfo(BaseModel):
    plan_name: str
    sms_cost: str
    description: str
    features: list[str]


class AllPlansResponse(BaseModel):
    plans: dict[str, PlanInfo]


class ChangePlanRequest(BaseModel):
    new_plan: str = Field(..., description="Plan name: Basic, Standard, Premium, or Enterprise")


class WalletResponse(BaseModel):
    user_id: uuid.UUID
    wallet_balance: str
    currency: str = "UGX"


class AddFundsRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to add to wallet (must be greater than 0)")
    payment_method: str | None = Field(default=None, description="Payment method used")
    reference_number: str | None = Field(default=None, description="Payment reference number")


class DeductFundsRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to deduct from wallet")
    reason: str | None = Field(default=None, description="Reason for deduction")


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    plan_sub: str
    wallet: str
    sms_cost: str
    is_active: bool


class UserStatsResponse(BaseModel):
    user_id: uuid.UUID
    plan: str
    wallet_balance: str
    sms_cost: str
    estimated_sms_count: int  # How many SMS can be sent with current balance


@router.get("/plans", response_model=AllPlansResponse)
def get_all_plans(current_user: CurrentUser) -> Any:
    """
    Get all available plans with their pricing and features.
    """
    plans_info = {
        plan_name: PlanInfo(
            plan_name=plan_name,
            sms_cost=plan_data["sms_cost"],
            description=plan_data["description"],
            features=plan_data["features"]
        )
        for plan_name, plan_data in PLANS.items()
    }
    return AllPlansResponse(plans=plans_info)


@router.get("/plan/current", response_model=PlanInfo)
def get_current_plan(current_user: CurrentUser) -> Any:
    """
    Get the current user's plan information.
    """
    plan_name = current_user.plan_sub or "Basic"
    
    if plan_name not in PLANS:
        plan_name = "Basic"
    
    plan_data = PLANS[plan_name]
    return PlanInfo(
        plan_name=plan_name,
        sms_cost=plan_data["sms_cost"],
        description=plan_data["description"],
        features=plan_data["features"]
    )


@router.post("/plan/change", response_model=UserProfileResponse)
def change_plan(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    plan_request: ChangePlanRequest
) -> Any:
    """
    Change user's subscription plan.
    
    Changing to a better plan will automatically update the SMS cost to a better rate.
    """
    new_plan = plan_request.new_plan
    
    # Validate plan exists
    if new_plan not in PLANS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan. Available plans: {', '.join(PLANS.keys())}"
        )
    
    # Get user from database
    user = session.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update plan and SMS cost
    old_plan = user.plan_sub
    old_sms_cost = user.sms_cost
    
    user.plan_sub = new_plan
    user.sms_cost = PLANS[new_plan]["sms_cost"]
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        plan_sub=user.plan_sub,
        wallet=user.wallet, # type: ignore
        sms_cost=user.sms_cost,
        is_active=user.is_active
    )


@router.post("/admin/{user_id}/add-funds", response_model=WalletResponse, dependencies=[Depends(get_current_active_superuser)])
def admin_add_funds_to_wallet(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    funds_request: AddFundsRequest
) -> Any:
    """
    Add funds to a specific user's wallet. (Admin only)
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_balance = float(user.wallet or "0.0")
    new_balance = current_balance + funds_request.amount
    
    user.wallet = f"{new_balance:.2f}"
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    transaction = Transaction(
        user_id=user.id,
        transaction_type="credit",
        amount=funds_request.amount,
        status="completed",
        payment_method=funds_request.payment_method or "admin_grant",
        reference_number=funds_request.reference_number,
        description=f"Admin added funds to wallet",
        balance_before=current_balance,
        balance_after=new_balance
    )
    session.add(transaction)
    session.commit()
    
    return WalletResponse(
        user_id=user.id,
        wallet_balance=user.wallet,
        currency="UGX"
    )


@router.post("/admin/{user_id}/deduct-funds", response_model=WalletResponse, dependencies=[Depends(get_current_active_superuser)])
def admin_deduct_funds_from_wallet(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    deduct_request: DeductFundsRequest
) -> Any:
    """
    Deduct funds from a specific user's wallet. (Admin only)
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_balance = float(user.wallet or "0.0")
    
    if current_balance < deduct_request.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Current balance: {current_balance} UGX, Required: {deduct_request.amount} UGX"
        )
    
    new_balance = current_balance - deduct_request.amount
    user.wallet = f"{new_balance:.2f}"
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    transaction = Transaction(
        user_id=user.id,
        transaction_type="debit",
        amount=deduct_request.amount,
        status="completed",
        description=deduct_request.reason or "Admin deduction",
        balance_before=current_balance,
        balance_after=new_balance
    )
    session.add(transaction)
    session.commit()
    
    return WalletResponse(
        user_id=user.id,
        wallet_balance=user.wallet,
        currency="UGX"
    )


@router.post("/admin/{user_id}/change-plan", response_model=UserProfileResponse, dependencies=[Depends(get_current_active_superuser)])
def admin_change_plan(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    plan_request: ChangePlanRequest
) -> Any:
    """
    Change a specific user's subscription plan. (Admin only)
    """
    new_plan = plan_request.new_plan
    
    if new_plan not in PLANS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan. Available plans: {', '.join(PLANS.keys())}"
        )
    
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.plan_sub = new_plan
    user.sms_cost = PLANS[new_plan]["sms_cost"]
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        plan_sub=user.plan_sub,
        wallet=user.wallet, # type: ignore
        sms_cost=user.sms_cost,
        is_active=user.is_active
    )


@router.get("/wallet", response_model=WalletResponse)
def get_wallet_balance(current_user: CurrentUser) -> Any:
    """
    Get current wallet balance.
    """
    return WalletResponse(
        user_id=current_user.id,
        wallet_balance=current_user.wallet or "0.0",
        currency="UGX"
    )


@router.post("/wallet/add-funds", response_model=WalletResponse)
def add_funds_to_wallet(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    funds_request: AddFundsRequest
) -> Any:
    """
    Add funds to wallet.
    
    This endpoint should be called after successful payment processing.
    """
    user = session.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Convert current wallet balance to float
    current_balance = float(user.wallet or "0.0")
    new_balance = current_balance + funds_request.amount
    
    # Update wallet
    user.wallet = f"{new_balance:.2f}"
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    # TODO: Create a transaction record here
    # from app.models import Transaction, TransactionCreate
    transaction = Transaction(
        user_id=user.id,
        transaction_type="credit",
        amount=funds_request.amount,
        status="completed",
        payment_method=funds_request.payment_method,
        reference_number=funds_request.reference_number,
        description=f"Added funds to wallet",
        balance_before=current_balance,
        balance_after=new_balance
    )
    session.add(transaction)
    session.commit()
    
    return WalletResponse(
        user_id=user.id,
        wallet_balance=user.wallet,
        currency="UGX"
    )


@router.post("/wallet/deduct-funds", response_model=WalletResponse)
def deduct_funds_from_wallet(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    deduct_request: DeductFundsRequest
) -> Any:
    """
    Deduct funds from wallet.
    
    This is typically used internally when sending SMS messages.
    """
    user = session.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Convert current wallet balance to float
    current_balance = float(user.wallet or "0.0")
    
    # Check if user has sufficient balance
    if current_balance < deduct_request.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Current balance: {current_balance} UGX, Required: {deduct_request.amount} UGX"
        )
    
    new_balance = current_balance - deduct_request.amount
    
    # Update wallet
    user.wallet = f"{new_balance:.2f}"
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    # TODO: Create a transaction record here
    transaction = Transaction(
        user_id=user.id,
        transaction_type="debit",
        amount=deduct_request.amount,
        status="completed",
        description=deduct_request.reason or "SMS charges",
        balance_before=current_balance,
        balance_after=new_balance
    )
    session.add(transaction)
    session.commit()
    
    return WalletResponse(
        user_id=user.id,
        wallet_balance=user.wallet,
        currency="UGX"
    )


@router.get("/profile", response_model=UserProfileResponse)
def get_user_profile(current_user: CurrentUser) -> Any:
    """
    Get user profile with plan and wallet information.
    """
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        plan_sub=current_user.plan_sub or "Basic",
        wallet=current_user.wallet or "0.0",
        sms_cost=current_user.sms_cost or "32",
        is_active=current_user.is_active
    )


@router.get("/stats", response_model=UserStatsResponse)
def get_user_stats(current_user: CurrentUser) -> Any:
    """
    Get user statistics including how many SMS messages can be sent with current balance.
    """
    wallet_balance = float(current_user.wallet or "0.0")
    sms_cost = float(current_user.sms_cost or "32")
    
    # Calculate how many SMS can be sent
    estimated_sms_count = int(wallet_balance / sms_cost) if sms_cost > 0 else 0
    
    return UserStatsResponse(
        user_id=current_user.id,
        plan=current_user.plan_sub or "Basic",
        wallet_balance=current_user.wallet or "0.0",
        sms_cost=current_user.sms_cost or "32",
        estimated_sms_count=estimated_sms_count
    )


class UpgradeRecommendationRequest(BaseModel):
    monthly_sms_volume: int = Field(..., gt=0, description="Estimated monthly SMS volume")


@router.post("/plan/upgrade-recommendation", response_model=dict)
def get_upgrade_recommendation(
    current_user: CurrentUser,
    request: UpgradeRecommendationRequest
) -> Any:
    """
    Get plan upgrade recommendation based on SMS usage.
    
    Calculates potential savings by upgrading to a better plan.
    """
    monthly_sms_volume = request.monthly_sms_volume
    current_plan = current_user.plan_sub or "Basic"
    current_sms_cost = float(current_user.sms_cost or "32")
    
    # Calculate costs for each plan
    recommendations = []
    current_monthly_cost = monthly_sms_volume * current_sms_cost
    
    for plan_name, plan_data in PLANS.items():
        plan_sms_cost = float(plan_data["sms_cost"])
        plan_monthly_cost = monthly_sms_volume * plan_sms_cost
        savings = current_monthly_cost - plan_monthly_cost
        savings_percentage = (savings / current_monthly_cost * 100) if current_monthly_cost > 0 else 0
        
        recommendations.append({
            "plan": plan_name,
            "sms_cost": plan_sms_cost,
            "monthly_cost": plan_monthly_cost,
            "savings": savings,
            "savings_percentage": round(savings_percentage, 2),
            "is_current": plan_name == current_plan,
            "is_better": savings > 0
        })
    
    # Sort by savings (best savings first)
    recommendations.sort(key=lambda x: x["savings"], reverse=True)
    
    return {
        "current_plan": current_plan,
        "monthly_sms_volume": monthly_sms_volume,
        "current_monthly_cost": current_monthly_cost,
        "recommendations": recommendations
    }


@router.get("/sms-cost", response_model=dict)
def get_sms_cost(current_user: CurrentUser) -> Any:
    """
    Get current SMS cost per message.
    """
    return {
        "user_id": current_user.id,
        "plan": current_user.plan_sub or "Basic",
        "sms_cost": current_user.sms_cost or "32",
        "currency": "UGX"
    }


class CheckBalanceRequest(BaseModel):
    sms_count: int = Field(..., gt=0, description="Number of SMS to send")


@router.post("/wallet/check-balance", response_model=dict)
def check_sufficient_balance(
    current_user: CurrentUser,
    request: CheckBalanceRequest
) -> Any:
    """
    Check if user has sufficient balance to send specified number of SMS.
    """
    sms_count = request.sms_count
    wallet_balance = float(current_user.wallet or "0.0")
    sms_cost = float(current_user.sms_cost or "32")
    total_cost = sms_count * sms_cost
    
    has_sufficient_balance = wallet_balance >= total_cost
    shortfall = max(0, total_cost - wallet_balance)
    
    return {
        "user_id": current_user.id,
        "wallet_balance": wallet_balance,
        "sms_cost": sms_cost,
        "sms_count": sms_count,
        "total_cost": total_cost,
        "has_sufficient_balance": has_sufficient_balance,
        "shortfall": shortfall,
        "currency": "UGX"
    }
