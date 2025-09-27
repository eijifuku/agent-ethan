"""Built-in tool implementations shipped with Agent Ethan."""

from .http_call import call as http_call
from .json_utils import parse_object as parse_json_object
from .mcp_call import invoke as mcp_call

__all__ = ["http_call", "mcp_call", "parse_json_object"]
