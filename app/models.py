from datetime import datetime
from typing import Optional
import uuid

from pydantic import EmailStr
from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy.orm import relationship


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)
    plan_sub: str | None = Field(default="Basic", max_length=255)
    wallet: str | None = Field(default="10.0", max_length=255)
    sms_cost: str | None = Field(default="32", max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
# class User(UserBase, table=True):
#     id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
#     hashed_password: str
#     items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)
#     api_keys: list["ApiKey"] = Relationship(back_populates="owner", cascade_delete=True)
#     templates: list["Template"] = Relationship(back_populates="owner", cascade_delete=True)
#     transactions: list["Transaction"] = Relationship(back_populates="user", cascade_delete=True)
#     sms_history: list["SmsHistory"] = Relationship(back_populates="user", cascade_delete=True)
class User(UserBase, table=True):
  id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
  hashed_password: str
  items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)
  api_keys: list["ApiKey"] = Relationship(back_populates="owner", cascade_delete=True)
  templates: list["Template"] = Relationship(back_populates="owner", cascade_delete=True)
  transactions: list["Transaction"] = Relationship(back_populates="user", cascade_delete=True)
  sms_history: list["SmsHistory"] = Relationship(back_populates="user", cascade_delete=True)
  contacts: list["Contact"] = Relationship(back_populates="user", cascade_delete=True)
  contact_groups: list["ContactGroup"] = Relationship(back_populates="user", cascade_delete=True)
  tickets: list["Ticket"] = Relationship(
    back_populates="user", 
    cascade_delete=True,
    sa_relationship_kwargs={"foreign_keys": "[Ticket.user_id]"}
)
    



# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: str | None = Field(default=None, min_length=1, max_length=255)  # type: ignore


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# ============================ API KEYS =====================================================


# Shared properties
class ApiKeyBase(SQLModel):
    name: str = Field(max_length=100)
    is_active: bool = True
    expires_at: Optional[datetime] = None
    permissions: str = Field(default="read,write", max_length=255)  # comma-separated


# Properties to receive on API key creation
class ApiKeyCreate(ApiKeyBase):
    pass


# Properties to receive on API key update
class ApiKeyUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    expires_at: Optional[datetime] = None
    permissions: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class ApiKey(ApiKeyBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    prefix: str = Field(index=True, max_length=8)  # e.g. "lk_abcd"
    hashed_key: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="api_keys")


# Properties to return via API, id is always required
class ApiKeyPublic(ApiKeyBase):
    id: uuid.UUID
    created_at: datetime
    user_id: uuid.UUID
    prefix: str  # Show prefix so users can identify keys
    plain_key: str | None = None  # Only populated on creation


class ApiKeysPublic(SQLModel):
    data: list[ApiKeyPublic]
    count: int


# ================================== Templates Models ===============================================

class TemplateBase(SQLModel):
    name: str = Field(max_length=255)
    content: str
    default: bool = False
    tag: str = Field(default="custom", max_length=200)


# Properties to receive on template creation
class TemplateCreate(TemplateBase):
    pass


# Properties to receive on template update
class TemplateUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    default: bool | None = None
    tag: str | None = Field(default=None, max_length=200)


# Database model, database table inferred from class name
class Template(TemplateBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="templates")


# Properties to return via API, id is always required
class TemplatePublic(TemplateBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime


class TemplatesPublic(SQLModel):
    data: list[TemplatePublic]
    count: int


# ====================================== TRANSACTION HISTORY ==========================================

class TransactionBase(SQLModel):
    transaction_type: str = Field(max_length=50)  # 'credit', 'debit', 'payment', 'refund'
    amount: float = Field(ge=0.0)  # Amount must be greater or equal to 0
    currency: str = Field(default="UGX", max_length=10)
    description: str | None = Field(default=None, max_length=500)
    status: str = Field(default="pending", max_length=50)  # 'pending', 'completed', 'failed', 'cancelled'
    payment_method: str | None = Field(default=None, max_length=100)  # 'mobile_money', 'card', 'bank_transfer'
    reference_number: str | None = Field(default=None, max_length=255)  # External payment reference


# Properties to receive on transaction creation
class TransactionCreate(TransactionBase):
    pass


# Properties to receive on transaction update
class TransactionUpdate(SQLModel):
    status: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    reference_number: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Transaction(TransactionBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    user: User | None = Relationship(back_populates="transactions")
    
    # Balance tracking
    balance_before: float | None = None
    balance_after: float | None = None


# Properties to return via API, id is always required
class TransactionPublic(TransactionBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    user_id: uuid.UUID
    balance_before: float | None
    balance_after: float | None


class TransactionsPublic(SQLModel):
    data: list[TransactionPublic]
    count: int


# ============================================ SMS HISTORY =======================================

class SmsHistoryBase(SQLModel):
    recipient: str = Field(max_length=20)  # Phone number
    message: str = Field(max_length=1000)
    status: str = Field(default="pending", max_length=50)  # 'pending', 'sent', 'delivered', 'failed'
    sms_count: int = Field(default=1, ge=1)  # Number of SMS units (160 chars = 1 SMS)
    cost: float = Field(ge=0)  # Cost of sending the SMS
    template_id: uuid.UUID | None = None  # Optional link to template used
    error_message: str | None = Field(default=None, max_length=500)
    delivery_status: str | None = Field(default=None, max_length=100)  # Provider delivery status
    external_id: str | None = Field(default=None, max_length=255)  # SMS provider message ID


# Properties to receive on SMS history creation
class SmsHistoryCreate(SmsHistoryBase):
    pass


# Properties to receive on SMS history update
class SmsHistoryUpdate(SQLModel):
    status: str | None = Field(default=None, max_length=50)
    delivery_status: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=500)
    external_id: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class SmsHistory(SmsHistoryBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: datetime | None = None  # When SMS was actually sent
    delivered_at: datetime | None = None  # When SMS was delivered
    
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    user: User | None = Relationship(back_populates="sms_history")


# Properties to return via API, id is always required
class SmsHistoryPublic(SmsHistoryBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None
    user_id: uuid.UUID


class SmsHistoriesPublic(SQLModel):
    data: list[SmsHistoryPublic]
    count: int


# ============================================ SMS BATCH OPERATIONS =======================================

class SmsBatchBase(SQLModel):
    name: str = Field(max_length=255)
    total_recipients: int = Field(ge=0)
    successful_sends: int = Field(default=0, ge=0)
    failed_sends: int = Field(default=0, ge=0)
    total_cost: float = Field(default=0.0, ge=0)
    status: str = Field(default="processing", max_length=50)  # 'processing', 'completed', 'failed'


# Properties to receive on batch creation
class SmsBatchCreate(SQLModel):
    name: str = Field(max_length=255)
    recipients: list[str]  # List of phone numbers
    message: str = Field(max_length=1000)
    template_id: uuid.UUID | None = None


# Database model
class SmsBatch(SmsBatchBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )


# Properties to return via API
class SmsBatchPublic(SmsBatchBase):
    id: uuid.UUID
    created_at: datetime
    completed_at: datetime | None
    user_id: uuid.UUID


class SmsBatchesPublic(SQLModel):
    data: list[SmsBatchPublic]
    count: int
    
    
#===================================== CONTACTS GROUPS =================================================

class ContactBase(SQLModel):
    name: str = Field(max_length=200)
    phone: str = Field(max_length=20)
    email: Optional[str] = Field(default=None, max_length=250)
    notes: str | None = Field(default=None, max_length=500)


# Properties to receive on contact creation
class ContactCreate(ContactBase):
    group_id: uuid.UUID | None = None


# Properties to receive on contact update
class ContactUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=250)
    notes: str | None = Field(default=None, max_length=500)
    group_id: uuid.UUID | None = None


# Database model
class Contact(ContactBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    user: User | None = Relationship(back_populates="contacts")
    
    group_id: uuid.UUID | None = Field(
        default=None, foreign_key="contactgroup.id", ondelete="SET NULL"
    )
    group: Optional["ContactGroup"] = Relationship(back_populates="contacts")


# Properties to return via API
class ContactPublic(ContactBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    user_id: uuid.UUID
    group_id: uuid.UUID | None


class ContactsPublic(SQLModel):
    data: list[ContactPublic]
    count: int

# ============= PROMO CODES ==========================================================
class PromoCodeBase(SQLModel):
    code: str = Field(unique=True, index=True, max_length=50)
    sms_cost: str = Field(max_length=50)
    is_active: bool = Field(default=True)
    expires_at: datetime | None = None
    max_uses: int | None = None
    current_uses: int = Field(default=0)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on promo code creation
class PromoCodeCreate(PromoCodeBase):
    pass


# Properties to receive on promo code update
class PromoCodeUpdate(SQLModel):
    sms_cost: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    expires_at: datetime | None = None
    max_uses: int | None = None
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class PromoCode(PromoCodeBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Properties to return via API, id is always required
class PromoCodePublic(PromoCodeBase):
    id: uuid.UUID
    created_at: datetime


class PromoCodesPublic(SQLModel):
    data: list[PromoCodePublic]
    count: int

# ============= Contact Groups ==========================================================

class ContactGroupBase(SQLModel):
    name: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=500)


# Properties to receive on group creation
class ContactGroupCreate(ContactGroupBase):
    pass


# Properties to receive on group update
class ContactGroupUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)


# Database model
class ContactGroup(ContactGroupBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    user: User | None = Relationship(back_populates="contact_groups")
    
    contacts: list["Contact"] = Relationship(back_populates="group")


# Properties to return via API
class ContactGroupPublic(ContactGroupBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    user_id: uuid.UUID
    contact_count: int = 0  # Computed field for number of contacts


class ContactGroupsPublic(SQLModel):
    data: list[ContactGroupPublic]
    count: int


#===================================== TICKETS SUPPORT =================================================

class TicketBase(SQLModel):
    subject: str = Field(max_length=255)
    description: str = Field(max_length=2000)
    status: str = Field(default="open", max_length=50)  # 'open', 'in_progress', 'resolved', 'closed'
    priority: str = Field(default="medium", max_length=50)  # 'low', 'medium', 'high', 'urgent'
    category: str | None = Field(default=None, max_length=100)  # 'billing', 'technical', 'general', etc.


# Properties to receive on ticket creation
class TicketCreate(TicketBase):
    pass


# Properties to receive on ticket update
class TicketUpdate(SQLModel):
    subject: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=50)
    priority: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)


# Database model
class Ticket(TicketBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    user: User | None = Relationship(
        back_populates="tickets",
        sa_relationship_kwargs={"foreign_keys": "[Ticket.user_id]"}
    )
    
    # Support agent assigned to ticket (optional)
    assigned_to: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    
    responses: list["TicketResponse"] = Relationship(
        back_populates="ticket", cascade_delete=True
    )


# Properties to return via API
class TicketPublic(TicketBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None
    user_id: uuid.UUID
    assigned_to: uuid.UUID | None
    response_count: int = 0  # Computed field


class TicketsPublic(SQLModel):
    data: list[TicketPublic]
    count: int


# ============= Ticket Responses =============

class TicketResponseBase(SQLModel):
    message: str = Field(max_length=2000)
    is_staff_response: bool = Field(default=False)  # True if from support staff


# Properties to receive on response creation
class TicketResponseCreate(TicketResponseBase):
    ticket_id: uuid.UUID


# Database model
class TicketResponse(TicketResponseBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    ticket_id: uuid.UUID = Field(
        foreign_key="ticket.id", nullable=False, ondelete="CASCADE", index=True
    )
    ticket: Ticket | None = Relationship(back_populates="responses")
    
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    user: User | None = Relationship()


# Properties to return via API
class TicketResponsePublic(TicketResponseBase):
    id: uuid.UUID
    created_at: datetime
    ticket_id: uuid.UUID
    user_id: uuid.UUID


class TicketResponsesPublic(SQLModel):
    data: list[TicketResponsePublic]
    count: int