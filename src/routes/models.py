"""Models list endpoint."""
from fastapi import APIRouter, Depends

from src.model_registry import model_registry
from src.models import ModelList
from src.routes.common import verify_auth

router = APIRouter()


@router.get("/v1/models", response_model=ModelList)
async def list_models(api_key: str = Depends(verify_auth)):
    """Return dynamic model list."""
    return ModelList(data=model_registry.get_models(api_key=api_key))
