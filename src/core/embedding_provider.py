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
        return [random.random() for _ in range(384)] # 384 is common for small models

class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    async def get_embedding(self, text: str) -> List[float]:
        # SentenceTransformer is synchronous, but we can run it directly here
        # since it's fast enough for local testing, or wrap in run_in_executor if needed.
        # For simplicity in this context, we'll run it directly.
        embedding = self.model.encode(text)
        return embedding.tolist()
