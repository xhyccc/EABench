from abc import ABC, abstractmethod
import asyncio
from typing import List
from openai import AsyncAzureOpenAI

class EmbeddingProvider(ABC):
    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        pass

    async def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts. Override for efficient batch API calls."""
        results = []
        for text in texts:
            results.append(await self.get_embedding(text))
        return results

    @abstractmethod
    def get_model_name(self) -> str:
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

    async def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Single API call for the whole batch, with exponential-backoff retry on 429."""
        from openai import RateLimitError
        backoff = 5.0
        for attempt in range(7):
            try:
                response = await self.client.embeddings.create(
                    input=texts,
                    model=self.deployment_name
                )
                return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
            except RateLimitError:
                if attempt == 6:
                    raise
                wait = backoff * (2 ** attempt)
                print(f"[embedding] 429 rate limit — retrying in {wait:.0f}s (attempt {attempt+1}/6)",
                      flush=True)
                await asyncio.sleep(wait)

    def get_model_name(self) -> str:
        return self.deployment_name

class MockEmbeddingProvider(EmbeddingProvider):
    async def get_embedding(self, text: str) -> List[float]:
        import random
        random.seed(len(text))
        return [random.random() for _ in range(384)]

    async def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        import random
        results = []
        for text in texts:
            random.seed(len(text))
            results.append([random.random() for _ in range(384)])
        return results

    def get_model_name(self) -> str:
        return "mock-embedding"

class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    async def get_embedding(self, text: str) -> List[float]:
        embedding = self.model.encode(text)
        return embedding.tolist()

    async def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """sentence-transformers natively supports batch encoding."""
        embeddings = self.model.encode(texts, batch_size=64, show_progress_bar=False)
        return embeddings.tolist()

    def get_model_name(self) -> str:
        return self.model_name
