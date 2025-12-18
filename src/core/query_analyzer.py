import json
from typing import Dict, Any, Optional
from .llm_provider import LLMProvider, Message
from ..config.agent_config import AgentConfig
from .logger import debug_logger

class QueryAnalyzer:
    def __init__(self, config: AgentConfig, llm: LLMProvider):
        self.config = config
        self.llm = llm

    async def analyze(self, query: str, domain: str, tool_name: str = None, user_profile: str = "") -> Dict[str, Any]:
        """
        Analyzes the user query using the configured LLM and domain-specific prompt.
        Returns a structured dictionary (DSL) representing the search strategy.
        """
        prompt_template = getattr(self.config.query_analyzer_prompt, domain, None)
        
        log_name = tool_name if tool_name else domain

        if not prompt_template:
            debug_logger.log_query_analysis(log_name, query, {"error": "No prompt configured", "strategy": "semantic"})
            return {"strategy": "semantic", "refined_query": query}

        prompt = prompt_template.replace("{query}", query)
        if "{user_profile}" in prompt:
            prompt = prompt.replace("{user_profile}", user_profile)
            
        messages = [Message(role="system", content=prompt)]

        try:
            # We pass empty tools list as we just want text generation (JSON)
            response = await self.llm.generate(messages, tools=[])
            content = response.content
            
            # Clean up markdown code blocks if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            result = json.loads(content)
            debug_logger.log_query_analysis(log_name, query, result)
            return result

        except Exception as e:
            debug_logger.log_query_analysis(log_name, query, {"error": str(e), "strategy": "semantic"})
            # Fallback on error
            return {"strategy": "semantic", "refined_query": query}
