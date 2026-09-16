from datetime import datetime

from pydantic import BaseModel


class AccountDeactivationResponse(BaseModel):
    account_state: str
    deactivated_at: datetime | None
    hard_delete_after: datetime | None

    model_config = {"from_attributes": True}
