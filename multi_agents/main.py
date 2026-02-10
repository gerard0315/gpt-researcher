from dotenv import load_dotenv
import sys
import os
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from multi_agents.agents import ChiefEditorAgent
import asyncio
import json
from gpt_researcher.utils.enum import Tone

# Run with LangSmith if API key is set
if os.environ.get("LANGCHAIN_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
load_dotenv()

def open_task(model_overrides: dict | None = None, llm_provider_credentials: dict | None = None):
    # Get the directory of the current script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Construct the absolute path to task.json
    task_json_path = os.path.join(current_dir, 'task.json')
    
    with open(task_json_path, 'r') as f:
        task = json.load(f)

    if not task:
        raise Exception("No task found. Please ensure a valid task.json file is present in the multi_agents directory and contains the necessary task information.")

    # Prefer per-request runtime model overrides.
    selected_llm = None
    if model_overrides:
        selected_llm = model_overrides.get("smart") or model_overrides.get("strategic")

    # Backwards-compatible fallback for standalone multi-agents runs.
    if not selected_llm:
        selected_llm = os.environ.get("STRATEGIC_LLM")

    if selected_llm and ":" in selected_llm:
        llm_provider, model_name = selected_llm.split(":", 1)
        task["model"] = model_name
        task["llm_provider"] = llm_provider
    elif selected_llm:
        task["model"] = selected_llm

    if llm_provider_credentials:
        task["llm_provider_credentials"] = llm_provider_credentials
    if model_overrides:
        task["model_overrides"] = model_overrides

    return task

async def run_research_task(
    query,
    websocket=None,
    stream_output=None,
    tone=Tone.Objective,
    headers=None,
    model_overrides: dict | None = None,
    llm_provider_credentials: dict | None = None,
):
    task = open_task(
        model_overrides=model_overrides,
        llm_provider_credentials=llm_provider_credentials,
    )
    task["query"] = query

    chief_editor = ChiefEditorAgent(task, websocket, stream_output, tone, headers)
    research_report = await chief_editor.run_research_task()

    if websocket and stream_output:
        await stream_output("logs", "research_report", research_report, websocket)

    return research_report

async def main():
    task = open_task()

    chief_editor = ChiefEditorAgent(task)
    research_report = await chief_editor.run_research_task(task_id=uuid.uuid4())

    return research_report

if __name__ == "__main__":
    asyncio.run(main())
