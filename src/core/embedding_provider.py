from abc import ABC, abstractmethod
from typing import List
from openai import AsyncAzureOpenAI

class EmbeddingProvider(ABC):
    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        pass

class AzureEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: str, azure_endpoint: str, api_version: str, deployment_name: str):
        self.client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint
        )
        self.deployment_name = deployment_name

    async def get_embedding(self, text: str) -> List[float]:
        response = await self.client.embeddings.create(
            input=text,
            model=self.deployment_name
        )
        return response.data[0].embedding

class MockEmbeddingProvider(EmbeddingProvider):
    async def get_embedding(self, text: str) -> List[float]:
        # Return a random vector or a deterministic one based on text length
        import random
        random.seed(len(text))
        return [random.random() for _ in range(1536)]
