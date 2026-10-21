
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PracticeSessionCreate(BaseModel):
    question_id: int = Field(gt=0)


class PracticeSessionUpdate(BaseModel):
    status: str = Field(
        pattern="^(pending|recording_uploaded|transcribing|evaluating|completed|failed)$"
    )


class PracticeSessionResponse(BaseModel):
    id: int
    user_id: int
    question_id: int
    status: str
    audio_key: str | None
    duration_seconds: float | None
    transcript: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SessionQuestionCreate(BaseModel):
    question_id: int = Field(gt=0)


class SessionQuestionResponse(BaseModel):
    id: int
    session_id: int
    question_id: int
    position: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
