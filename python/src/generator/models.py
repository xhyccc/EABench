from pydantic import BaseModel, Field
from typing import List, Optional

class StoryConfig(BaseModel):
    company_name: str
    industry: str
    company_size: str = "small" # small, medium, large
    num_users: int = 5
    duration_days: int = 7
    eval_batch_size: int = 5
    key_events: List[str] = Field(default_factory=list)
    description: str
    
class GenerationOutput(BaseModel):
    tenant_id: str
    base_path: str
    summary: str
