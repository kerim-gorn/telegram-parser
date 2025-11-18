from fastapi import APIRouter

from app.schemas import ChatHistoryRequest, ScheduleResponse
from app.services import schedule_parse_history

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/parse/history", response_model=ScheduleResponse)
async def parse_history_endpoint(payload: ChatHistoryRequest) -> ScheduleResponse:
    task_id = schedule_parse_history(
        account_phone=payload.account_phone,
        chat_entity=payload.chat_entity,
        days=payload.days or 7,
    )
    return ScheduleResponse(task_id=task_id)


