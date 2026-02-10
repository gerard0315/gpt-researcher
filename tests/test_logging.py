import pytest
from unittest.mock import AsyncMock
from fastapi import WebSocket
from backend.server.server_utils import CustomLogsHandler
import os
import json

@pytest.mark.asyncio
async def test_custom_logs_handler():
    # Mock websocket
    mock_websocket = AsyncMock()
    mock_websocket.send_json = AsyncMock()
    
    # Test initialization
    handler = CustomLogsHandler(mock_websocket, "test_query")
    
    # Verify log file creation
    assert os.path.exists(handler.log_file)
    assert os.path.exists(handler.log_dir)
    assert os.path.exists(handler.events_file)
    
    # Test sending log data
    test_data = {
        "type": "logs",
        "message": "Test log message"
    }
    
    await handler.send_json(test_data)
    
    # Verify websocket was called with correct data
    mock_websocket.send_json.assert_called_once_with(test_data)
    
    # Verify log file contents
    with open(handler.log_file, 'r') as f:
        log_data = json.load(f)
        assert len(log_data['events']) == 1
        assert log_data['events'][0]['data'] == test_data 

    with open(handler.events_file, 'r') as f:
        log_data = json.load(f)
        assert len(log_data['events']) == 1

    assert os.path.exists(handler.detailed_events_file)

@pytest.mark.asyncio
async def test_content_update():
    """Test handling of non-log type data that updates content"""
    mock_websocket = AsyncMock()
    mock_websocket.send_json = AsyncMock()
    
    handler = CustomLogsHandler(mock_websocket, "test_query")
    
    # Test content update
    content_data = {
        "query": "test query",
        "sources": ["source1", "source2"],
        "report": "test report"
    }
    
    await handler.send_json(content_data)
    
    mock_websocket.send_json.assert_called_once_with(content_data)
    
    # Verify log file contents
    with open(handler.log_file, 'r') as f:
        log_data = json.load(f)
        assert log_data['content']['query'] == "test query"
        assert log_data['content']['sources'] == ["source1", "source2"]
        assert log_data['content']['report'] == "test report"

    with open(handler.events_file, 'r') as f:
        log_data = json.load(f)
        assert log_data['content']['query'] == "test query"


@pytest.mark.asyncio
async def test_streamed_report_and_cost_updates_are_aggregated_into_content_snapshot():
    mock_websocket = AsyncMock()
    mock_websocket.send_json = AsyncMock()

    handler = CustomLogsHandler(mock_websocket, "test_query")

    await handler.send_json({"type": "report", "output": "first chunk "})
    await handler.send_json({"type": "report", "output": "second chunk"})
    await handler.send_json({"type": "cost", "data": {"total_cost": "$0.02262052"}})

    with open(handler.log_file, "r") as f:
        log_data = json.load(f)
        assert log_data["content"]["report"] == "first chunk second chunk"
        assert log_data["content"]["costs"] == pytest.approx(0.02262052, rel=1e-9)
        assert "type" not in log_data["content"]
        assert "output" not in log_data["content"]
