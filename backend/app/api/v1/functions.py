from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.errors import APIError
from app.functions import (
    FunctionNotFoundError,
    get_registered_function,
    list_registered_functions,
)
from app.models.user import User
from app.schemas.records import (
    RegisteredFunctionListResponse,
    RegisteredFunctionResponse,
)

router = APIRouter(prefix="/functions", tags=["registered-functions"])


@router.get("", response_model=RegisteredFunctionListResponse)
async def list_functions(
    _: User = Depends(get_current_user),
) -> RegisteredFunctionListResponse:
    return RegisteredFunctionListResponse(
        data=[item.metadata() for item in list_registered_functions()]
    )


@router.get("/{name}/versions/{version}", response_model=RegisteredFunctionResponse)
async def get_function(
    name: str,
    version: str,
    _: User = Depends(get_current_user),
) -> RegisteredFunctionResponse:
    try:
        return RegisteredFunctionResponse(
            **get_registered_function(name, version).metadata()
        )
    except FunctionNotFoundError as error:
        raise APIError(
            status_code=404,
            code=error.code,
            message=error.message,
            details=error.details,
        ) from error
