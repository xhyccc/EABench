import logging
import json
from typing import Any, Dict, List
import streamlit as st

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("EABench")

class DebugLogger:
    def __init__(self):
        self.logs = []

    def log_llm_call(self, messages: List[Dict[str, Any]]):
        entry = {
            "type": "LLM Call",
            "content": messages
        }
        self.logs.append(entry)
        logger.info(f"LLM Call: {json.dumps(messages, indent=2)}")
        self._update_streamlit()

    def log_llm_response(self, response: Any):
        # Handle object with content/tool_calls attributes
        content = getattr(response, "content", str(response))
        tool_calls = getattr(response, "tool_calls", None)
        
        entry = {
            "type": "LLM Response",
            "content": content,
            "tool_calls": [t.model_dump() for t in tool_calls] if tool_calls else None
        }
        self.logs.append(entry)
        logger.info(f"LLM Response: {content}")
        if tool_calls:
            logger.info(f"Tool Calls: {tool_calls}")
        self._update_streamlit()

    def log_tool_call(self, tool_name: str, arguments: Dict[str, Any]):
        entry = {
            "type": "Tool Call",
            "tool": tool_name,
            "arguments": arguments
        }
        self.logs.append(entry)
        logger.info(f"Tool Call: {tool_name} with args {arguments}")
        self._update_streamlit()

    def log_tool_result(self, tool_name: str, result: str):
        entry = {
            "type": "Tool Result",
            "tool": tool_name,
            "result": result
        }
        self.logs.append(entry)
        logger.info(f"Tool Result ({tool_name}): {result}")
        self._update_streamlit()

    def _update_streamlit(self):
        if "debug_logs" not in st.session_state:
            st.session_state.debug_logs = []
        st.session_state.debug_logs = self.logs

# Global logger instance
debug_logger = DebugLogger()
