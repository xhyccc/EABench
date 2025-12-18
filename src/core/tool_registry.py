from typing import Callable, Dict, Any, Type
from pydantic import BaseModel
import inspect

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, args_schema: Type[BaseModel]):
        def decorator(func: Callable):
            self._tools[name] = func
            # Generate JSON schema from Pydantic model
            schema = args_schema.model_json_schema()
            self._schemas[name] = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": func.__doc__ or "",
                    "parameters": schema
                }
            }
            return func
        return decorator

    def get_tool(self, name: str) -> Callable:
        return self._tools.get(name)

    def get_schemas(self) -> list[Dict[str, Any]]:
        return list(self._schemas.values())

# Global registry instance
registry = ToolRegistry()
