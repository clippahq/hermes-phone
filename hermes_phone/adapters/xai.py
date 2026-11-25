"""xAI Grok LLM adapter with configurable reasoning effort.

Supports grok-4.3 (fast, effort: "none" for live turns) and grok-4.7 (deep reasoning).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

from . import LLMAdapter, LLMMessage


log = logging.getLogger(__name__)

XAI_API_BASE = "https://api.x.ai/v1"


class XAILLMAdapter:
    """Streaming LLM via xAI Grok with OpenAI-compatible API.
    
    Args:
        api_key: xAI API key
        model: Model name ("grok-4.3", "grok-4.7", etc.)
        reasoning_effort: Reasoning effort level ("none", "low", "medium", "high", "xhigh")
        temperature: Sampling temperature (0.0 to 2.0)
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "grok-4.3",
        reasoning_effort: str | None = "none",
        temperature: float = 0.7,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self._response_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._tool_calls_queue: asyncio.Queue[list[dict]] = asyncio.Queue()
    
    async def send_message(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        """Send a conversation turn to Grok and start streaming response."""
        import httpx
        
        # Convert LLMMessage to OpenAI format
        formatted_messages = []
        for msg in messages:
            formatted = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.tool_calls:
                formatted["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                formatted["tool_call_id"] = msg.tool_call_id
            formatted_messages.append(formatted)
        
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "stream": True,
        }
        
        # Add reasoning effort if model supports it
        effort = reasoning_effort or self.reasoning_effort
        if effort and effort != "none":
            payload["reasoning"] = {"effort": effort}
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        # Stream the response
        asyncio.create_task(self._stream_response(payload, headers))
    
    async def _stream_response(self, payload: dict, headers: dict) -> None:
        """Background task to stream tokens from Grok."""
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{XAI_API_BASE}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    
                    tool_calls_accumulator: dict[int, dict] = {}
                    
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        
                        delta = choices[0].get("delta", {})
                        
                        # Handle content tokens
                        if "content" in delta and delta["content"]:
                            await self._response_queue.put(delta["content"])
                        
                        # Handle tool calls
                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls_accumulator:
                                    tool_calls_accumulator[idx] = {
                                        "id": tc.get("id", ""),
                                        "type": tc.get("type", "function"),
                                        "function": {"name": "", "arguments": ""},
                                    }
                                
                                if "function" in tc:
                                    if "name" in tc["function"]:
                                        tool_calls_accumulator[idx]["function"]["name"] = tc["function"]["name"]
                                    if "arguments" in tc["function"]:
                                        tool_calls_accumulator[idx]["function"]["arguments"] += tc["function"]["arguments"]
                    
                    # Send accumulated tool calls
                    if tool_calls_accumulator:
                        tool_calls_list = [tool_calls_accumulator[i] for i in sorted(tool_calls_accumulator.keys())]
                        await self._tool_calls_queue.put(tool_calls_list)
                    
        except Exception as e:  # noqa: BLE001
            log.error("xAI stream error: %s", e)
        finally:
            await self._response_queue.put(None)
    
    async def receive_tokens(self) -> AsyncIterator[str]:
        """Receive streaming response tokens."""
        while True:
            token = await self._response_queue.get()
            if token is None:
                break
            yield token
    
    async def receive_tool_calls(self) -> list[dict[str, Any]]:
        """Receive tool calls from the LLM."""
        try:
            return await asyncio.wait_for(self._tool_calls_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return []
    
    async def close(self) -> None:
        """Close the LLM connection."""
        # Clear queues
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        while not self._tool_calls_queue.empty():
            try:
                self._tool_calls_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
