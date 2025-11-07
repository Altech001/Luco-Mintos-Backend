from fastapi import APIRouter


from app.api.routes import items, login, private, smssend, users, utils, api_keys, templates, userdata, promocodes, contactsgroup,tickets
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_router.include_router(templates.router)
api_router.include_router(userdata.router)
api_router.include_router(smssend.router)
api_router.include_router(promocodes.router)
api_router.include_router(contactsgroup.router)
api_router.include_router(tickets.router)




if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
