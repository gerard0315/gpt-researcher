import { useRef, useState, useEffect, useCallback } from 'react';
import { Data, ChatBoxSettings, QuestionData } from '../types/data';
import { getHost } from '../helpers/getHost';
import { DEFAULT_ADVANCED_SETTINGS } from '../constants/researchSettings';

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 1000;

export const useWebSocket = (
  setOrderedData: React.Dispatch<React.SetStateAction<Data[]>>,
  setAnswer: React.Dispatch<React.SetStateAction<string>>,
  setLoading: React.Dispatch<React.SetStateAction<boolean>>,
  setShowHumanFeedback: React.Dispatch<React.SetStateAction<boolean>>,
  setQuestionForHuman: React.Dispatch<React.SetStateAction<boolean | true>>
) => {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const heartbeatInterval = useRef<number>();

  // Reconnection state
  const taskIdRef = useRef<string | null>(null);
  const eventCountRef = useRef<number>(0);
  const reconnectAttemptsRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<number>();
  const intentionalCloseRef = useRef<boolean>(false);
  const loadingRef = useRef<boolean>(false);

  // Keep loadingRef in sync with the loading state
  // (we need a ref because the onclose handler captures stale closure)
  const setLoadingWrapped: typeof setLoading = useCallback((value) => {
    if (typeof value === 'function') {
      setLoading((prev) => {
        const next = value(prev);
        loadingRef.current = next;
        return next;
      });
    } else {
      loadingRef.current = value;
      setLoading(value);
    }
  }, [setLoading]);

  // Cleanup function for heartbeat and socket on unmount
  useEffect(() => {
    return () => {
      intentionalCloseRef.current = true;
      // Clear heartbeat interval
      if (heartbeatInterval.current) {
        clearInterval(heartbeatInterval.current);
      }
      // Clear reconnect timeout
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }

      // Close socket on unmount if it exists and is open
      if (socket && socket.readyState === WebSocket.OPEN) {
        console.log('Closing WebSocket due to component unmount');
        socket.close(1000, "Component unmounted");
      }
    };
  }, [socket]);

  const startHeartbeat = (ws: WebSocket) => {
    // Clear any existing heartbeat
    if (heartbeatInterval.current) {
      clearInterval(heartbeatInterval.current);
    }

    // Start new heartbeat
    heartbeatInterval.current = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 30000); // Send ping every 30 seconds
  };

  const getWsUri = () => {
    let fullHost = getHost();
    const protocol = fullHost.includes('https') ? 'wss:' : 'ws:';
    const cleanHost = fullHost.replace('http://', '').replace('https://', '');
    return `${protocol}//${cleanHost}/ws`;
  };

  const setupMessageHandler = (ws: WebSocket) => {
    ws.onmessage = (event) => {
      try {
        // Handle ping response
        if (event.data === 'pong') return;

        // Try to parse JSON data
        console.log(`Received WebSocket message: ${event.data.substring(0, 100)}...`);
        const data = JSON.parse(event.data);

        // Store task_id for reconnection
        if (data.type === 'task_id') {
          taskIdRef.current = data.output;
          console.log(`Received task_id: ${data.output}`);
          return;
        }

        // Count events for reconnection cursor
        eventCountRef.current += 1;

        if (data.type === 'error') {
          console.error(`Server error: ${data.output}`);
        } else if (data.type === 'human_feedback' && data.content === 'request') {
          setQuestionForHuman(data.output);
          setShowHumanFeedback(true);
        } else {
          const contentAndType = `${data.content}-${data.type}`;
          setOrderedData((prevOrder) => [...prevOrder, { ...data, contentAndType }]);

          if (data.type === 'report') {
            const outputStr = typeof data.output === 'string' ? data.output : JSON.stringify(data.output);
            setAnswer((prev: string) => prev + outputStr);
          } else if (data.type === 'path') {
            setLoadingWrapped(false);
            // Research done — clear task_id so we don't try to reconnect
            taskIdRef.current = null;
          }
        }
      } catch (error) {
        console.error('Error parsing WebSocket message:', error, event.data);
      }
    };
  };

  const attemptReconnect = () => {
    if (intentionalCloseRef.current) return;
    if (!taskIdRef.current) return;
    if (!loadingRef.current) return;
    if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
      console.log('Max reconnect attempts reached, giving up');
      setLoadingWrapped(false);
      return;
    }

    const attempt = reconnectAttemptsRef.current + 1;
    const delay = BASE_RECONNECT_DELAY_MS * Math.pow(2, attempt - 1);
    console.log(`Scheduling reconnect attempt ${attempt}/${MAX_RECONNECT_ATTEMPTS} in ${delay}ms`);

    reconnectTimeoutRef.current = window.setTimeout(() => {
      reconnectAttemptsRef.current = attempt;
      const taskId = taskIdRef.current;
      const lastEventIndex = eventCountRef.current;

      if (!taskId) return;

      console.log(`Reconnecting to task ${taskId} (last_event_index=${lastEventIndex})`);
      const ws_uri = getWsUri();
      const ws = new WebSocket(ws_uri);
      setSocket(ws);

      ws.onopen = () => {
        console.log('Reconnect WebSocket opened, sending reconnect command');
        reconnectAttemptsRef.current = 0;  // Reset on successful connect
        const message = `reconnect ${JSON.stringify({ log_id: taskId, last_event_index: lastEventIndex })}`;
        ws.send(message);
        startHeartbeat(ws);
      };

      setupMessageHandler(ws);

      ws.onclose = (event) => {
        console.log(`Reconnect WebSocket closed: code=${event.code}, reason=${event.reason}`);
        if (heartbeatInterval.current) {
          clearInterval(heartbeatInterval.current);
        }
        setSocket(null);
        // Try again if still not intentional
        attemptReconnect();
      };

      ws.onerror = (error) => {
        console.error('Reconnect WebSocket error:', error);
        if (heartbeatInterval.current) {
          clearInterval(heartbeatInterval.current);
        }
      };
    }, delay);
  };

  const initializeWebSocket = useCallback((
    promptValue: string,
    chatBoxSettings: ChatBoxSettings
  ) => {
    // Close existing socket if any
    if (socket && socket.readyState === WebSocket.OPEN) {
      console.log('Closing existing WebSocket connection');
      intentionalCloseRef.current = true;
      socket.close(1000, "New connection requested");
    }

    // Reset reconnection state for a new research
    intentionalCloseRef.current = false;
    taskIdRef.current = null;
    eventCountRef.current = 0;
    reconnectAttemptsRef.current = 0;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    const storedConfig = localStorage.getItem('apiVariables');
    const apiVariables = storedConfig ? JSON.parse(storedConfig) : {};

    if (typeof window !== 'undefined') {

      const ws_uri = getWsUri();

      console.log(`Creating new WebSocket connection to ${ws_uri}`);
      const newSocket = new WebSocket(ws_uri);
      setSocket(newSocket);

      // WebSocket connection opened handler
      newSocket.onopen = () => {
        console.log('WebSocket connection opened');

        const domainFilters = JSON.parse(localStorage.getItem('domainFilters') || '[]');
        const domains = domainFilters ? domainFilters.map((domain: any) => domain.value) : [];
        const { report_type, report_source, tone, mcp_enabled, mcp_configs, mcp_strategy, model_config, advanced_settings } = chatBoxSettings;
        const mergedAdvancedSettings = {
          ...DEFAULT_ADVANCED_SETTINGS,
          ...(advanced_settings || {}),
        };

        // Start a new research
        try {
          console.log(`Starting new research for: ${promptValue}`);
          const dataToSend = {
            task: promptValue,
            report_type,
            report_source,
            tone,
            query_domains: domains,
            mcp_enabled: mcp_enabled || false,
            mcp_strategy: mcp_strategy || "fast",
            mcp_configs: mcp_configs || [],
            model_config: model_config || { fast: "official_gpt4o", smart: "kimi_k2_turbo", strategic: "bltcy_gpt52pro" },
            advanced_settings: mergedAdvancedSettings,
          };

          // Make sure we have a properly formatted command with a space after start
          const message = `start ${JSON.stringify(dataToSend)}`;
          console.log(`Sending start message, length: ${message.length}`);
          newSocket.send(message);
        } catch (error) {
          console.error("Error preparing start message:", error);
        }

        startHeartbeat(newSocket);
      };

      setupMessageHandler(newSocket);

      newSocket.onclose = (event) => {
        console.log(`WebSocket connection closed: code=${event.code}, reason=${event.reason}`);
        if (heartbeatInterval.current) {
          clearInterval(heartbeatInterval.current);
        }
        setSocket(null);
        // Attempt auto-reconnect if research is still in progress
        attemptReconnect();
      };

      newSocket.onerror = (error) => {
        console.error('WebSocket error:', error);
        if (heartbeatInterval.current) {
          clearInterval(heartbeatInterval.current);
        }
      };
    }
  }, [socket, setOrderedData, setAnswer, setLoadingWrapped, setShowHumanFeedback, setQuestionForHuman]);

  // Expose intentionalCloseRef so the stop button can prevent reconnection
  const markIntentionalClose = useCallback(() => {
    intentionalCloseRef.current = true;
    taskIdRef.current = null;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
  }, []);

  return { socket, setSocket, initializeWebSocket, markIntentionalClose };
};
