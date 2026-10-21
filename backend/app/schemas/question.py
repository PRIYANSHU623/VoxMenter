from pydantic import BaseModel, Field, ConfigDict


class QuestionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    category: str = Field(min_length=1, max_length=100)
    difficulty: str = Field(default="Beginner", max_length=50)
    is_active: bool = True

class QuestionResponse(BaseModel):
    
    id: int
    title: str
    description: str | None
    category: str
    difficulty: str
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)