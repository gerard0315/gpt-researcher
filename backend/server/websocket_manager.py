import asyncio
import datetime
import json
import logging
import traceback
from typing import Dict, List

from fastapi import WebSocket

from report_type import BasicReport, DetailedReport

from gpt_researcher.utils.enum import ReportType, Tone
from gpt_researcher.actions import stream_output  # Import stream_output
from multi_agents.main import run_research_task
from .server_utils import CustomLogsHandler
import os

# Capture initial environment variables for restoration
INITIAL_ENV = {
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
    "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
    "FAST_LLM": os.environ.get("FAST_LLM"),
    "SMART_LLM": os.environ.get("SMART_LLM"),
    "STRATEGIC_LLM": os.environ.get("STRATEGIC_LLM"),
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

    async def start_streaming(self, task, report_type, report_source, source_urls, document_urls, tone, websocket, headers=None, query_domains=[], mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], api_provider="official"):
        """Start streaming the output."""
        tone = Tone[tone]
        # add customized JSON config file path here
        config_path = "default"

        # Pass MCP parameters to run_agent
        report = await run_agent(
            task, report_type, report_source, source_urls, document_urls, tone, websocket, 
            headers=headers, query_domains=query_domains, config_path=config_path,
            mcp_enabled=mcp_enabled, mcp_strategy=mcp_strategy, mcp_configs=mcp_configs,
            api_provider=api_provider
        )
        return report

async def run_agent(task, report_type, report_source, source_urls, document_urls, tone: Tone, websocket, stream_output=stream_output, headers=None, query_domains=[], config_path="", return_researcher=False, mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], api_provider="official"):
    """Run the agent."""    
    # Create logs handler for this research task
    logs_handler = CustomLogsHandler(websocket, task)

    # Configure API Provider
    if api_provider == "bltcy":
        print(f"🔄 Switching to BLTCY API Provider")
        # Use BLTCY key if available, otherwise fallback to empty string (which will cause error later likely)
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_KEY_BLTCY", "")
        os.environ["OPENAI_BASE_URL"] = "https://api.bltcy.ai/v1"
        os.environ["FAST_LLM"] = "openai:gpt-5.2-pro"
        os.environ["SMART_LLM"] = "openai:gpt-5.2-pro"
        os.environ["STRATEGIC_LLM"] = "openai:gpt-5.2-pro"
    elif api_provider == "official":
        print(f"🔄 Switching to Official OpenAI Provider")
        # Restore initial values
        if INITIAL_ENV["OPENAI_API_KEY"]:
            os.environ["OPENAI_API_KEY"] = INITIAL_ENV["OPENAI_API_KEY"]
        else:
             os.environ.pop("OPENAI_API_KEY", None)
        
        if INITIAL_ENV["OPENAI_BASE_URL"]:
            os.environ["OPENAI_BASE_URL"] = INITIAL_ENV["OPENAI_BASE_URL"]
        else:
            # If it wasn't set initially, remove it to fallback to default
            os.environ.pop("OPENAI_BASE_URL", None)
            
        # Restore LLM models
        for key in ["FAST_LLM", "SMART_LLM", "STRATEGIC_LLM"]:
            if INITIAL_ENV[key]:
                os.environ[key] = INITIAL_ENV[key]
            else:
                os.environ.pop(key, None)

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
            headers=headers
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
        )
        report = await researcher.run()

    if report_type != "multi_agents" and return_researcher:
        return report, researcher.gpt_researcher
    else:
        return report
