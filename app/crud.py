import string
import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.security import get_password_hash, verify_password
from app.models import ApiKeyUpdate, Item, ItemCreate, User, UserCreate, UserUpdate, ApiKey, ApiKeyCreate

import secrets


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        return None
    if not verify_password(password, db_user.hashed_password):
        return None
    return db_user


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item



#============= API KEY CRUD ==========================================================#


def generate_api_key() -> str:
    """Generate a secure 32-char API key with 'lk_' prefix"""
    alphabet = string.ascii_letters + string.digits
    return "lk_" + "".join(secrets.choice(alphabet) for _ in range(32))


def create_api_key(*, session: Session, api_key_create: ApiKeyCreate, user_id: uuid.UUID) -> ApiKey:
    """Create a new API key for a user"""
    plain_key = generate_api_key()
    hashed_key = get_password_hash(plain_key)
    db_obj = ApiKey.model_validate(
        api_key_create,
        update={
            "prefix": plain_key[:6],
            "hashed_key": hashed_key,
            "user_id": user_id,
        }
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_api_key(*, session: Session, db_api_key: ApiKey, api_key_in: ApiKeyUpdate) -> Any:
    """Update an existing API key (e.g., name, is_active status)"""
    api_key_data = api_key_in.model_dump(exclude_unset=True)
    db_api_key.sqlmodel_update(api_key_data)
    session.add(db_api_key)
    session.commit()
    session.refresh(db_api_key)
    return db_api_key


def get_api_key_by_prefix(*, session: Session, prefix: str) -> ApiKey | None:
    """Get an API key by its prefix"""
    statement = select(ApiKey).where(ApiKey.prefix == prefix)
    session_api_key = session.exec(statement).first()
    return session_api_key


def authenticate_api_key(*, session: Session, key: str) -> ApiKey | None:
    """Authenticate an API key and return the ApiKey object if valid"""
    prefix = key[:6]
    db_api_key = get_api_key_by_prefix(session=session, prefix=prefix)
    if not db_api_key:
        return None
    if not db_api_key.is_active:
        return None
    if not verify_password(key, db_api_key.hashed_key):
        return None
    return db_api_key


def get_user_api_keys(*, session: Session, user_id: uuid.UUID) -> list[ApiKey]:
    """Get all API keys for a specific user"""
    statement = select(ApiKey).where(ApiKey.user_id == user_id)
    return list(session.exec(statement).all())


#=================================================================================================