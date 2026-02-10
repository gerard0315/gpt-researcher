import asyncio
import datetime
import json
import logging
import traceback
from typing import Dict, List, Any

from fastapi import WebSocket

from report_type import BasicReport, DetailedReport

from gpt_researcher.utils.enum import ReportType, Tone
from gpt_researcher.actions import stream_output  # Import stream_output
from multi_agents.main import run_research_task
from .server_utils import CustomLogsHandler
import os

# Capture initial environment variables
INITIAL_ENV = {
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
    "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
    "OPENAI_BLT_URL": os.environ.get("OPENAI_BLT_URL"),
    "OPENAI_KEY_BLTCY": os.environ.get("OPENAI_KEY_BLTCY"),
    "KIMI_API_KEY": os.environ.get("KIMI_API_KEY"),
    "RETRIEVER": os.environ.get("RETRIEVER"),
}

logger = logging.getLogger(__name__)

class WebSocketManager:
    """Manage websockets"""

    def __init__(self):
        """Initialize the WebSocketManager class."""
        self.active_connections: List[WebSocket] = []
        self.sender_tasks: Dict[WebSocket, asyncio.Task] = {}
        self.message_queues: Dict[WebSocket, asyncio.Queue] = {}

    async def start_sender(self, websocket: WebSocket):
        """Start the sender task."""
        queue = self.message_queues.get(websocket)
        if not queue:
            return

        while True:
            try:
                message = await queue.get()
                if message is None:  # Shutdown signal
                    break
                    
                if websocket in self.active_connections:
                    if message == "ping":
                        await websocket.send_text("pong")
                    else:
                        await websocket.send_text(message)
                else:
                    break
            except Exception as e:
                print(f"Error in sender task: {e}")
                break

    async def connect(self, websocket: WebSocket):
        """Connect a websocket."""
        try:
            await websocket.accept()
            self.active_connections.append(websocket)
            self.message_queues[websocket] = asyncio.Queue()
            self.sender_tasks[websocket] = asyncio.create_task(
                self.start_sender(websocket))
        except Exception as e:
            print(f"Error connecting websocket: {e}")
            if websocket in self.active_connections:
                await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Disconnect a websocket."""
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                
                # Cancel sender task if it exists
                if websocket in self.sender_tasks:
                    try:
                        self.sender_tasks[websocket].cancel()
                        await self.message_queues[websocket].put(None)
                    except Exception as e:
                        logger.error(f"Error canceling sender task: {e}")
                    finally:
                        # Always try to clean up regardless of errors
                        if websocket in self.sender_tasks:
                            del self.sender_tasks[websocket]
                
                # Clean up message queue
                if websocket in self.message_queues:
                    del self.message_queues[websocket]
                
                # Finally close the WebSocket
                try:
                    await websocket.close()
                except Exception as e:
                    logger.info(f"WebSocket already closed: {e}")
        except Exception as e:
            logger.error(f"Error during WebSocket disconnection: {e}")
            # Still try to close the connection if possible
            try:
                await websocket.close()
            except:
                pass  # If this fails too, there's nothing more we can do

    async def start_streaming(self, task, report_type, report_source, source_urls, document_urls, tone, websocket, headers=None, query_domains=[], mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], model_config=None, advanced_settings=None):
        """Start streaming the output."""
        tone = Tone[tone]
        # add customized JSON config file path here
        config_path = "default"

        # Pass MCP parameters to run_agent
        report = await run_agent(
            task, report_type, report_source, source_urls, document_urls, tone, websocket,
            headers=headers, query_domains=query_domains, config_path=config_path,
            mcp_enabled=mcp_enabled, mcp_strategy=mcp_strategy, mcp_configs=mcp_configs,
            model_config=model_config, advanced_settings=advanced_settings
        )
        return report

MODEL_PRESET_MAP: Dict[str, Dict[str, str]] = {
    "official_gpt52pro": {"llm": "openai:gpt-5.2-pro", "provider": "openai"},
    "bltcy_gpt52pro": {"llm": "bltcy:gpt-5.2-pro", "provider": "bltcy"},
    "official_gpt4o": {"llm": "openai:gpt-4o", "provider": "openai"},
    "kimi_k2_turbo": {"llm": "moonshot:kimi-k2-turbo-preview", "provider": "moonshot"},
}

DEFAULT_MODEL_CONFIG = {"fast": "official_gpt4o", "smart": "kimi_k2_turbo", "strategic": "bltcy_gpt52pro"}
MODEL_CONFIG_TIERS = ("fast", "smart", "strategic")
ADVANCED_SETTING_BOUNDS: Dict[str, tuple[int, int]] = {
    "deep_research_breadth": (1, 12),
    "deep_research_depth": (1, 6),
    "deep_research_concurrency": (1, 12),
    "max_search_results_per_query": (1, 20),
    "max_iterations": (1, 10),
}


def _validate_model_config(model_config: Any) -> Dict[str, str]:
    """Validate incoming model config and return normalized config."""
    if model_config is None:
        return dict(DEFAULT_MODEL_CONFIG)

    if not isinstance(model_config, dict):
        raise ValueError("Invalid model_config: expected an object with fast/smart/strategic fields.")

    unknown_keys = sorted(set(model_config.keys()) - set(MODEL_CONFIG_TIERS))
    if unknown_keys:
        raise ValueError(f"Invalid model_config keys: {', '.join(unknown_keys)}.")

    missing_keys = [key for key in MODEL_CONFIG_TIERS if key not in model_config]
    if missing_keys:
        raise ValueError(f"Missing model_config keys: {', '.join(missing_keys)}.")

    invalid_presets = []
    normalized: Dict[str, str] = {}
    for key in MODEL_CONFIG_TIERS:
        preset_name = model_config.get(key)
        if preset_name not in MODEL_PRESET_MAP:
            invalid_presets.append(f"{key}={preset_name}")
        else:
            normalized[key] = str(preset_name)

    if invalid_presets:
        valid_values = ", ".join(sorted(MODEL_PRESET_MAP.keys()))
        raise ValueError(
            f"Unsupported model preset(s): {', '.join(invalid_presets)}. "
            f"Supported values: {valid_values}."
        )

    return normalized


def _build_model_runtime_config(model_config: Dict[str, str]) -> tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """Resolve model overrides and provider credentials from a validated model config."""
    openai_api_key = os.getenv("OPENAI_API_KEY") or INITIAL_ENV.get("OPENAI_API_KEY")
    openai_base_url = os.getenv("OPENAI_BASE_URL") or INITIAL_ENV.get("OPENAI_BASE_URL")
    bltcy_api_key = os.getenv("OPENAI_KEY_BLTCY") or INITIAL_ENV.get("OPENAI_KEY_BLTCY")
    bltcy_base_url = os.getenv("OPENAI_BLT_URL") or INITIAL_ENV.get("OPENAI_BLT_URL")
    kimi_api_key = os.getenv("KIMI_API_KEY") or INITIAL_ENV.get("KIMI_API_KEY")

    model_overrides: Dict[str, str] = {}
    used_providers: set[str] = set()

    for tier in MODEL_CONFIG_TIERS:
        preset = MODEL_PRESET_MAP[model_config[tier]]
        model_overrides[tier] = preset["llm"]
        used_providers.add(preset["provider"])

    provider_credentials: Dict[str, Dict[str, str]] = {}
    missing_requirements: list[str] = []

    if "openai" in used_providers:
        if not openai_api_key:
            missing_requirements.append("OPENAI_API_KEY (required for OpenAI presets)")
        else:
            provider_credentials["openai"] = {"openai_api_key": openai_api_key}
            if openai_base_url:
                provider_credentials["openai"]["openai_api_base"] = openai_base_url

    if "bltcy" in used_providers:
        bltcy_base = bltcy_base_url or "https://api.bltcy.ai/v1"
        if not bltcy_api_key:
            missing_requirements.append("OPENAI_KEY_BLTCY (required for BLTCY presets)")
        else:
            provider_credentials["bltcy"] = {
                "openai_api_key": bltcy_api_key,
                "openai_api_base": bltcy_base,
            }

    if "moonshot" in used_providers:
        if not kimi_api_key:
            missing_requirements.append("KIMI_API_KEY (required for Moonshot/Kimi presets)")
        else:
            provider_credentials["moonshot"] = {
                "openai_api_key": kimi_api_key,
                "openai_api_base": "https://api.moonshot.cn/v1",
            }

    if missing_requirements:
        raise ValueError("Model preset credentials are missing: " + "; ".join(missing_requirements))

    return model_overrides, provider_credentials

def _validate_advanced_settings(advanced_settings: Any) -> Dict[str, int]:
    """Validate incoming advanced_settings and return normalized config override values."""
    if advanced_settings is None:
        return {}

    if not isinstance(advanced_settings, dict):
        raise ValueError("Invalid advanced_settings: expected an object.")

    normalized: Dict[str, int] = {}

    for key, bounds in ADVANCED_SETTING_BOUNDS.items():
        if key not in advanced_settings:
            continue

        raw_value = advanced_settings.get(key)
        if isinstance(raw_value, bool):
            raise ValueError(f"Invalid advanced_settings.{key}: expected an integer.")

        try:
            int_value = int(raw_value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid advanced_settings.{key}: expected an integer.")

        min_value, max_value = bounds
        if int_value < min_value or int_value > max_value:
            raise ValueError(
                f"Invalid advanced_settings.{key}: expected value between {min_value} and {max_value}."
            )

        normalized[key] = int_value

    return normalized


async def run_agent(task, report_type, report_source, source_urls, document_urls, tone: Tone, websocket, stream_output=stream_output, headers=None, query_domains=[], config_path="", return_researcher=False, mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], model_config=None, advanced_settings=None):
    """Run the agent."""
    # Create logs handler for this research task
    logs_handler = CustomLogsHandler(websocket, task)

    validated_model_config = _validate_model_config(model_config)
    model_overrides, provider_credentials = _build_model_runtime_config(validated_model_config)
    config_overrides = _validate_advanced_settings(advanced_settings)
    print(
        "🔧 Model config: "
        f"FAST={model_overrides['fast']}, "
        f"SMART={model_overrides['smart']}, "
        f"STRATEGIC={model_overrides['strategic']}"
    )
    if config_overrides:
        print(f"🔧 Advanced settings: {config_overrides}")

    # Set up MCP configuration if enabled
    if mcp_enabled:
        # If MCP is enabled but no configs were provided by the UI, fall back to env.
        if not mcp_configs:
            raw_env_mcp_servers = os.getenv("MCP_SERVERS", "")
            if raw_env_mcp_servers:
                try:
                    parsed_servers = json.loads(raw_env_mcp_servers)
                    if isinstance(parsed_servers, list):
                        mcp_configs = parsed_servers
                except Exception:
                    mcp_configs = []

        if mcp_configs:
            current_retriever = os.getenv("RETRIEVER", "tavily")
            if "mcp" not in current_retriever:
                # Add MCP to existing retrievers
                os.environ["RETRIEVER"] = f"{current_retriever},mcp"

            # Set MCP strategy
            os.environ["MCP_STRATEGY"] = mcp_strategy

            print(f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)")
            await logs_handler.send_json({
                "type": "logs",
                "content": "mcp_init",
                "output": f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)"
            })

    # Initialize researcher based on report type
    if report_type == "multi_agents":
        report = await run_research_task(
            query=task, 
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            stream_output=stream_output, 
            tone=tone, 
            headers=headers,
            model_overrides=model_overrides,
            llm_provider_credentials=provider_credentials,
        )
        report = report.get("report", "")

    elif report_type == ReportType.DetailedReport.value:
        researcher = DetailedReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            model_overrides=model_overrides,
            llm_provider_credentials=provider_credentials,
            config_overrides=config_overrides,
        )
        report = await researcher.run()
        
    else:
        researcher = BasicReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            model_overrides=model_overrides,
            llm_provider_credentials=provider_credentials,
            config_overrides=config_overrides,
        )
        report = await researcher.run()

    if report_type != "multi_agents" and return_researcher:
        return report, researcher.gpt_researcher
    else:
        return report
