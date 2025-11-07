import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import ApiKey, ApiKeyCreate, ApiKeyPublic, ApiKeysPublic, ApiKeyUpdate, Message
from app import crud

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("/", response_model=ApiKeysPublic)
def read_api_keys(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve API keys.
    """
    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(ApiKey)
        count = session.exec(count_statement).one()
        statement = select(ApiKey).offset(skip).limit(limit)
        api_keys = session.exec(statement).all()
    else:
        count_statement = (
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.user_id == current_user.id)
        )
        count = session.exec(count_statement).one()
        statement = (
            select(ApiKey)
            .where(ApiKey.user_id == current_user.id)
            .offset(skip)
            .limit(limit)
        )
        api_keys = session.exec(statement).all()

    return ApiKeysPublic(data=api_keys, count=count)  # type: ignore


@router.get("/{api_key_id}", response_model=ApiKeyPublic)
def read_api_key(
    session: SessionDep, current_user: CurrentUser, api_key_id: uuid.UUID
) -> Any:
    """
    Get API key by ID.
    """
    api_key = session.get(ApiKey, api_key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if not current_user.is_superuser and (api_key.user_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")
    return api_key


@router.post("/", response_model=ApiKeyPublic, status_code=status.HTTP_201_CREATED)
def create_api_key(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    api_key_in: ApiKeyCreate,
) -> Any:
    """
    Create new API key. Returns the plain key only once - save it securely!
    """
    api_key = crud.create_api_key(
        session=session, api_key_create=api_key_in, user_id=current_user.id
    )

    # Generate plain key to return (only once!)
    plain_key = crud.generate_api_key()
    # But wait — crud.create_api_key already generated it!
    # So we need to return it from CRUD or regenerate safely

    # Better: modify CRUD to return plain_key
    # Or: regenerate here and override
    # Let's override for clarity

    plain_key = crud.generate_api_key()  # You already generate in CRUD
    api_key.prefix = plain_key[:6]
    api_key.hashed_key = crud.get_password_hash(plain_key)  # ← FIX: use imported function

    session.add(api_key)
    session.commit()
    session.refresh(api_key)

    return ApiKeyPublic(**api_key.model_dump(), plain_key=plain_key)


@router.put("/{api_key_id}", response_model=ApiKeyPublic)
def update_api_key(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    api_key_id: uuid.UUID,
    api_key_in: ApiKeyUpdate,
) -> Any:
    """
    Update an API key.
    """
    api_key = session.get(ApiKey, api_key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if not current_user.is_superuser and (api_key.user_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")
    update_dict = api_key_in.model_dump(exclude_unset=True)
    api_key.sqlmodel_update(update_dict)
    session.add(api_key)
    session.commit()
    session.refresh(api_key)
    return api_key


@router.delete("/{api_key_id}", response_model=Message)
def delete_api_key(
    session: SessionDep, current_user: CurrentUser, api_key_id: uuid.UUID
) -> Any:
    """
    Delete an API key.
    """
    api_key = session.get(ApiKey, api_key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if not current_user.is_superuser and (api_key.user_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")
    session.delete(api_key)
    session.commit()
    return Message(message="API key deleted successfully")


# ==================== REGENERATE KEY ====================

@router.post("/{api_key_id}/regenerate", response_model=ApiKeyPublic)
def regenerate_api_key(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    api_key_id: uuid.UUID,
) -> Any:
    """
    Regenerate an API key. Returns the new plain key only once.
    """
    api_key = session.get(ApiKey, api_key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if not current_user.is_superuser and (api_key.user_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    # Generate new key
    plain_key = crud.generate_api_key()
    api_key.prefix = plain_key[:6]
    api_key.hashed_key = crud.get_password_hash(plain_key)
    # Optional: update created_at
    # api_key.created_at = datetime.utcnow()

    session.add(api_key)
    session.commit()
    session.refresh(api_key)

    return ApiKeyPublic(**api_key.model_dump(), plain_key=plain_key)