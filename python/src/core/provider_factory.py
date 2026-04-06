"""Canonical provider factory for EABench.

Both the CLI (run_eval.py) and the web UI (app.py) must import from here so
that LLM / embedding construction logic lives in exactly one place.

Env-var precedence (both names are accepted for backward-compatibility):
    API key   : AZURE_OPENAI_API_KEY  | AZURE_API_KEY
    Endpoint  : AZURE_OPENAI_ENDPOINT | AZURE_ENDPOINT
    API ver   : AZURE_OPENAI_API_VERSION | AZURE_API_VERSION  (default: 2024-02-15-preview)
    Emb ver   : AZURE_EMB_API_VERSION (falls back to API ver above)
    OpenAI key: OPENAI_API_KEY
    OpenAI URL: OPENAI_API_BASE | OPENAI_BASE_URL (optional)
"""

import asyncio
import os

from ..config.agent_config import AgentConfig, ProviderType
from ..config.tenant_config import TenantConfig
from .azure_provider import AzureOpenAIProvider
from .embedding_provider import AzureEmbeddingProvider, LocalEmbeddingProvider
from .openai_provider import OpenAIProvider
from .search_engine import SearchEngine
from ..sandbox.local_sandbox import LocalSandbox


def _azure_key() -> str | None:
    return os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")


def _azure_endpoint() -> str | None:
    return os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_ENDPOINT")


def _azure_api_version() -> str:
    return (
        os.getenv("AZURE_OPENAI_API_VERSION")
        or os.getenv("AZURE_API_VERSION")
        or "2024-02-15-preview"
    )


def build_llm(agent_config: AgentConfig, temperature: float | None = None):
    """Build the LLM provider declared in *agent_config* using env vars.

    *temperature* overrides the value in the config when provided.

    Raises:
        ValueError: if required env vars are missing or the provider is unknown.
    """
    model_cfg = agent_config.model
    t = temperature if temperature is not None else model_cfg.parameters.get("temperature", 0.7)

    if model_cfg.provider == ProviderType.AZURE:
        key = _azure_key()
        endpoint = _azure_endpoint()
        ver = _azure_api_version()
        if not key:
            raise ValueError("Azure LLM: set AZURE_OPENAI_API_KEY or AZURE_API_KEY")
        if not endpoint:
            raise ValueError("Azure LLM: set AZURE_OPENAI_ENDPOINT or AZURE_ENDPOINT")
        return AzureOpenAIProvider(
            api_key=key,
            azure_endpoint=endpoint,
            deployment_name=model_cfg.name,
            api_version=ver,
            temperature=t,
        )

    if model_cfg.provider == ProviderType.OPENAI:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OpenAI LLM: set OPENAI_API_KEY")
        return OpenAIProvider(
            api_key=key,
            base_url=os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL"),
            model=model_cfg.name,
            temperature=t,
        )

    raise ValueError(f"Unsupported LLM provider: {model_cfg.provider!r}")


def build_embedding(agent_config: AgentConfig):
    """Build the embedding provider declared in *agent_config* using env vars.

    Raises:
        ValueError: if the embedding section is missing, required env vars are
                    absent, or the provider is unknown — never silently returns
                    a no-op mock that would produce empty search results.
    """
    emb = agent_config.embedding
    if not emb:
        raise ValueError(
            f"Agent config '{agent_config.id}' has no embedding section. "
            "All agent configs must declare an embedding model."
        )

    if emb.provider == ProviderType.AZURE:
        key = _azure_key()
        endpoint = _azure_endpoint()
        ver = (
            os.getenv("AZURE_EMB_API_VERSION")
            or _azure_api_version()
        )
        if not key:
            raise ValueError("Azure embedding: set AZURE_OPENAI_API_KEY or AZURE_API_KEY")
        if not endpoint:
            raise ValueError("Azure embedding: set AZURE_OPENAI_ENDPOINT or AZURE_ENDPOINT")
        return AzureEmbeddingProvider(
            api_key=key,
            azure_endpoint=endpoint,
            api_version=ver,
            deployment_name=emb.model,
        )

    if emb.provider == ProviderType.LOCAL:
        return LocalEmbeddingProvider(model_name=emb.model)

    raise ValueError(
        f"Embedding provider '{emb.provider}' in agent config '{agent_config.id}' "
        "is not supported. Supported providers: azure, local."
    )


def build_resources(agent_config: AgentConfig, tenant_config: TenantConfig, llm=None):
    """Build and return all runtime resources needed to run the agent.

    Constructs the LLM (unless *llm* is supplied as an override), embedding
    provider, sandbox, and search engine.  The search engine is returned
    **without** running ``index_all()`` — callers must do that themselves
    (it is async and context-dependent).

    Args:
        agent_config: Loaded agent configuration.
        tenant_config: Loaded tenant configuration.
        llm: Pre-built LLM provider.  When ``None`` (default),
             ``build_llm(agent_config)`` is called automatically.

    Returns:
        ``(llm, embedding_provider, sandbox, search_engine)``
    """
    if llm is None:
        llm = build_llm(agent_config)
    embedding = build_embedding(agent_config)
    sandbox = LocalSandbox(tenant_config)
    sandbox.start()
    search_engine = SearchEngine(tenant_config, embedding, sandbox)
    return llm, embedding, sandbox, search_engine
