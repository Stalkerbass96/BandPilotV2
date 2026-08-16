"""Tuning routes — expose the tunings catalog for the frontend selector.

遵循 "auto-detect + user override" 原则：本端点只读地列出全部定弦供用户
选择覆盖自动检测结果；真正的覆盖行为发生在 repair 请求传入 ``tuning_id``
时（见 :mod:`fretpilot.api.routes.projects`）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from fretpilot.api.deps import get_current_user
from fretpilot.db.models import User
from fretpilot.knowledge.tunings import TuningRegistry

router = APIRouter()


class TuningInfo(BaseModel):
    """定弦选择器条目——只暴露前端需要的字段。"""

    id: str
    name: str
    display_name: str
    string_count: int
    min_pitch: int
    max_pitch: int


@router.get("", response_model=dict)
def list_tunings(user: User = Depends(get_current_user)) -> dict:
    """Return the full tunings catalog (12 profiles) for the selector UI."""
    tunings = TuningRegistry.default().all_tunings()
    items = [
        TuningInfo(
            id=t.id,
            name=t.name,
            display_name=t.display_name,
            string_count=t.string_count,
            min_pitch=t.min_pitch,
            max_pitch=t.max_pitch,
        ).model_dump()
        for t in tunings
    ]
    return {"code": 0, "data": {"items": items}, "message": "ok"}


__all__ = ["router"]
