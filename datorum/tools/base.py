from pydantic import BaseModel, Field, PrivateAttr, model_validator


def agent_tool(func):
    """Decorator to mark a BaseToolBox method as an OpenAI API tool."""
    func._is_tool = True
    return func


class BaseToolBox(BaseModel):
    ...