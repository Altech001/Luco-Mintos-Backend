# type: ignore
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional, Set, Dict, Any

import africastalking
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    User, Template, SmsHistory, Transaction
)

from dotenv import load_dotenv
import os

load_dotenv()

at_live_username = os.getenv("AT_LIVE_USERNAME")
at_live_api_key = os.getenv("AT_LIVE_API_KEY")
at_sender_id = os.getenv("AT_SENDER_ID")


router = APIRouter(prefix="/sms", tags=["sms"])

# ====================== Africa's Talking Init ======================

africastalking.initialize(
    username=at_live_username,
    api_key=at_live_api_key,
)
sms = africastalking.SMS

# ====================== WebSocket Manager ======================
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        disconnected = set()
        for conn in self.active_connections:
            try:
                await conn.send_text(json.dumps(message))
            except:
                disconnected.add(conn)
        self.active_connections -= disconnected

manager = ConnectionManager()

# ====================== Pydantic Models ======================
class RecipientResponse(BaseModel):
    number: str
    status: str
    statusCode: int
    cost: str
    messageId: Optional[str] = None

class SendSMSResponse(BaseModel):
    batch_id: Optional[str] = None
    summary: str
    total_sent: int
    total_cost_ugx: Decimal
    recipients: List[RecipientResponse]

class SendSMSRequest(BaseModel):
    to: List[str] = Field(..., description="Phone numbers in international format")
    message: str = Field(..., min_length=1, max_length=1600)
    from_: Optional[str] = Field(None, alias="from")
    template_id: Optional[uuid.UUID] = None  # Changed from str to uuid.UUID
    enqueue: bool = True

# ====================== Helper: Deduct Wallet + Log Transaction ======================
def deduct_and_log_wallet(
    session: Session,
    user: User,
    total_cost: Decimal,
    description: str = "SMS Send"
):
    current_balance = Decimal(user.wallet or "0.0")
    if current_balance < total_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds: {current_balance} UGX < {total_cost} UGX"
        )

    new_balance = current_balance - total_cost
    user.wallet = str(new_balance.quantize(Decimal("0.01")))

    # Log transaction
    transaction = Transaction(
        user_id=user.id,
        transaction_type="debit",
        amount=float(total_cost),
        description=description,
        balance_before=float(current_balance),
        balance_after=float(new_balance),
        status="completed"
    )
    session.add(transaction)
    session.add(user)
    session.commit()
    session.refresh(user)

# ====================== MAIN SEND SMS ENDPOINT (SYNC + REAL-TIME) ======================
@router.post("/send", response_model=SendSMSResponse)
async def send_sms(
    payload: SendSMSRequest,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    current_user: CurrentUser,
):
    """
    Send SMS with:
    - Wallet deduction
    - Transaction + SMS history logging
    - Template support
    - Real-time delivery via WebSocket
    - No Celery needed
    """
    # Resolve template
    final_message = payload.message
    template_id = payload.template_id
    
    if template_id:
        template = session.get(Template, template_id)  # Now template_id is already a UUID
        if not template or template.owner_id != current_user.id:
            raise HTTPException(404, "Template not found")
        final_message = template.content

    # Calculate SMS units (160 chars = 1 SMS)
    msg_len = len(final_message)
    sms_units = (msg_len // 153) + (1 if msg_len % 153 else 0) if msg_len > 160 else 1
    recipients_count = len(payload.to)
    cost_per_sms = Decimal(current_user.sms_cost or "32")
    total_cost = cost_per_sms * sms_units * recipients_count

    # Deduct wallet
    deduct_and_log_wallet(session, current_user, total_cost, f"SMS to {recipients_count} recipients")

    sender = payload.from_ or at_sender_id or "ATUpdates"

    try:
        # Send via Africa's Talking
        response = sms.send(
            message=final_message,
            recipients=payload.to,
            sender_id=sender,
            enqueue=1 if payload.enqueue else 0,
        )

        data = response["SMSMessageData"]
        recipients_data = data["Recipients"]

        # Log each SMS to history
        for r in recipients_data:
            cost = Decimal(r["cost"].replace("UGX ", "").strip())
            history = SmsHistory(
                user_id=current_user.id,
                recipient=r["number"],
                message=final_message,
                status=r["status"].lower(),
                sms_count=sms_units,
                cost=float(cost),
                external_id=r.get("messageId"),
                template_id=template_id,  # This is now a UUID or None
                sent_at=datetime.utcnow()
            )
            session.add(history)

        session.commit()

        # Broadcast success
        await manager.broadcast({
            "event": "sms_batch_sent",
            "user_id": str(current_user.id),
            "summary": data["Message"],
            "total_sent": len(recipients_data),
            "total_cost": str(total_cost),
            "timestamp": datetime.utcnow().isoformat()
        })

        # Format response
        recipients_resp = [
            RecipientResponse(
                number=r["number"],
                status=r["status"],
                statusCode=r["statusCode"],
                cost=r["cost"],
                messageId=r.get("messageId")
            )
            for r in recipients_data
        ]

        return SendSMSResponse(
            batch_id=None,
            summary=data["Message"],
            total_sent=len(recipients_data),
            total_cost_ugx=total_cost,
            recipients=recipients_resp
        )

    except Exception as e:
        # Rollback wallet on failure
        session.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"SMS gateway failed: {str(e)}"
        ) from e

# ====================== WEBSOCKET FOR REAL-TIME UPDATES ======================
@router.websocket("/ws")
async def sms_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ====================== DELIVERY REPORT WEBHOOK (Africa's Talking → Your Server) ======================
@router.post("/webhook/delivery-reports")
async def delivery_report_webhook(report: Dict[str, Any], session: SessionDep):
    """
    Set this URL in Africa's Talking dashboard:
    https://yourdomain.com/api/v1/sms/webhook/delivery-reports
    """
    phone = report.get("phoneNumber")
    status = report.get("status")
    message_id = report.get("id")
    failure = report.get("failureReason")

    # Update SmsHistory
    history = session.exec(
        select(SmsHistory).where(SmsHistory.external_id == message_id)
    ).first()

    if history:
        history.status = status.lower()
        history.error_message = failure
        history.delivered_at = datetime.utcnow() if "Delivered" in status else None
        session.add(history)
        session.commit()

    # Broadcast update
    await manager.broadcast({
        "event": "delivery_update",
        "phoneNumber": phone,
        "status": status,
        "messageId": message_id,
        "failureReason": failure
    })

    return {"status": "received"}