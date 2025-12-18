from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
import yaml

class ProviderType(str, Enum):
    OPENAI = "openai"
    AZURE = "azure"
    ANTHROPIC = "anthropic"
    LOCAL = "local"

class ModelConfig(BaseModel):
    provider: ProviderType
    name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)

class EmbeddingConfig(BaseModel):
    provider: ProviderType
    model: str
    parameters: Dict[str, Any] = Field(default_factory=dict)

class ToolConfig(BaseModel):
    definitions: List[str]
    config: Dict[str, Any] = Field(default_factory=dict)

class FlowStrategy(str, Enum):
    REACT = "react"
    CHAIN = "chain"
    PLANNING_DAG = "planning_dag"

class FlowConfig(BaseModel):
    strategy: FlowStrategy
    max_turns: int = 10

class QueryAnalyzerPromptConfig(BaseModel):
    search_email: str = Field(default="")
    search_file: str = Field(default="")
    search_chat: str = Field(default="")
    search_meeting: str = Field(default="")
    search_people: str = Field(default="")

class AgentConfig(BaseModel):
    id: str
    version: str
    model: ModelConfig
    embedding: Optional[EmbeddingConfig] = None
    system_prompt: str
    query_analyzer_prompt: QueryAnalyzerPromptConfig = Field(default_factory=QueryAnalyzerPromptConfig)
    dynamic_keys: List[str] = Field(default_factory=list)
    tools: ToolConfig
    flow: FlowConfig

    @classmethod
    def from_yaml(cls, path: str) -> "AgentConfig":
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)
