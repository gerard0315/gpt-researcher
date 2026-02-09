#!/bin/bash
#
# GPT-Researcher Service Management Script
# Usage:
#   ./service.sh start   - Activate venv and start backend + frontend
#   ./service.sh stop    - Stop all services and deactivate venv
#   ./service.sh restart - Fully stop and restart services (stays in venv)
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PID_FILE="$SCRIPT_DIR/.service_pids"
BACKEND_PORT=${BACKEND_PORT:-8000}
FRONTEND_PORT=${FRONTEND_PORT:-3000}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Activate virtual environment
activate_venv() {
    if [ -d "$VENV_DIR" ]; then
        log_info "Activating virtual environment..."
        source "$VENV_DIR/bin/activate"
    else
        log_error "Virtual environment not found at $VENV_DIR"
        log_info "Create it with: python -m venv .venv && source .venv/bin/activate && pip install -e ."
        exit 1
    fi
}

# Deactivate virtual environment
deactivate_venv() {
    if [ -n "$VIRTUAL_ENV" ]; then
        log_info "Deactivating virtual environment..."
        deactivate 2>/dev/null || true
    fi
}

# Kill a process and all its children
kill_process_tree() {
    local pid=$1
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        # Kill child processes first
        pkill -P "$pid" 2>/dev/null || true
        # Then kill the main process
        kill "$pid" 2>/dev/null || true
        # Wait a moment then force kill if still running
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
}

# Stop all services by finding processes on the ports
stop_services() {
    log_info "Stopping services..."
    
    # Kill by PID file if exists
    if [ -f "$PID_FILE" ]; then
        while read -r pid; do
            if [ -n "$pid" ]; then
                log_info "Killing process tree for PID: $pid"
                kill_process_tree "$pid"
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi
    
    # Also kill any processes on our ports (belt and suspenders)
    log_info "Checking for processes on ports $BACKEND_PORT and $FRONTEND_PORT..."
    
    # Kill backend (uvicorn on port 8000)
    local backend_pids=$(lsof -ti:$BACKEND_PORT 2>/dev/null)
    if [ -n "$backend_pids" ]; then
        log_info "Killing backend processes on port $BACKEND_PORT: $backend_pids"
        echo "$backend_pids" | xargs kill -9 2>/dev/null || true
    fi
    
    # Kill frontend (next.js on port 3000)
    local frontend_pids=$(lsof -ti:$FRONTEND_PORT 2>/dev/null)
    if [ -n "$frontend_pids" ]; then
        log_info "Killing frontend processes on port $FRONTEND_PORT: $frontend_pids"
        echo "$frontend_pids" | xargs kill -9 2>/dev/null || true
    fi
    
    # Kill any remaining uvicorn or next processes from this project
    pkill -f "uvicorn.*backend.server" 2>/dev/null || true
    pkill -f "next.*gpt-researcher" 2>/dev/null || true
    
    sleep 1
    log_info "Services stopped."
}

# Start services
start_services() {
    log_info "Starting services..."
    
    # Clear old PID file
    rm -f "$PID_FILE"
    
    cd "$SCRIPT_DIR"
    
    # Start backend
    log_info "Starting backend server on port $BACKEND_PORT..."
    python -m uvicorn backend.server.app:app --host=0.0.0.0 --port=$BACKEND_PORT --reload &
    local backend_pid=$!
    echo "$backend_pid" >> "$PID_FILE"
    log_info "Backend started with PID: $backend_pid"
    
    # Start frontend (if nextjs directory exists and has node_modules)
    if [ -d "$SCRIPT_DIR/frontend/nextjs" ]; then
        cd "$SCRIPT_DIR/frontend/nextjs"
        if [ -d "node_modules" ]; then
            log_info "Starting frontend on port $FRONTEND_PORT..."
            npm run dev &
            local frontend_pid=$!
            echo "$frontend_pid" >> "$PID_FILE"
            log_info "Frontend started with PID: $frontend_pid"
        else
            log_warn "Frontend node_modules not found. Run 'cd frontend/nextjs && npm install' first."
        fi
        cd "$SCRIPT_DIR"
    fi
    
    log_info "Services started!"
    log_info "Backend:  http://localhost:$BACKEND_PORT"
    log_info "Frontend: http://localhost:$FRONTEND_PORT"
    log_info ""
    log_info "Use './service.sh stop' to stop services"
}

# Initialize environment and install dependencies
init_environment() {
    log_info "Initializing GPT-Researcher environment..."
    
    cd "$SCRIPT_DIR"
    
    # Create virtual environment if it doesn't exist
    if [ ! -d "$VENV_DIR" ]; then
        log_info "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi
    
    # Activate virtual environment
    activate_venv
    
    # Upgrade pip
    log_info "Upgrading pip..."
    pip install --upgrade pip
    
    # Install Python dependencies
    log_info "Installing Python dependencies..."
    if [ -f "pyproject.toml" ]; then
        pip install -e .
    elif [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    else
        log_error "No pyproject.toml or requirements.txt found!"
        exit 1
    fi
    
    # Install frontend dependencies
    if [ -d "$SCRIPT_DIR/frontend/nextjs" ]; then
        log_info "Installing frontend (Next.js) dependencies..."
        cd "$SCRIPT_DIR/frontend/nextjs"
        
        # Check if npm is available
        if command -v npm &> /dev/null; then
            npm install
            log_info "Frontend dependencies installed."
        else
            log_warn "npm not found. Please install Node.js and npm first."
        fi
        
        cd "$SCRIPT_DIR"
    else
        log_warn "Frontend directory not found at $SCRIPT_DIR/frontend/nextjs"
    fi
    
    log_info "Initialization complete!"
    log_info "You can now run './service.sh start' to start the services."
}

# Main command handler
case "$1" in
    init)
        init_environment
        ;;
    start)
        activate_venv
        start_services
        log_info "Virtual environment is active. Run 'deactivate' or './service.sh stop' to exit."
        # Keep the script running to maintain the venv context
        echo ""
        log_info "Press Ctrl+C to stop services..."
        wait
        ;;
    stop)
        stop_services
        deactivate_venv
        log_info "All services stopped and virtual environment deactivated."
        ;;
    restart)
        activate_venv
        stop_services
        sleep 2
        start_services
        log_info "Services restarted. Virtual environment remains active."
        echo ""
        log_info "Press Ctrl+C to stop services..."
        wait
        ;;
    status)
        echo "Checking service status..."
        echo ""
        echo "Backend (port $BACKEND_PORT):"
        lsof -i:$BACKEND_PORT 2>/dev/null || echo "  Not running"
        echo ""
        echo "Frontend (port $FRONTEND_PORT):"
        lsof -i:$FRONTEND_PORT 2>/dev/null || echo "  Not running"
        echo ""
        echo "Virtual environment: ${VIRTUAL_ENV:-Not active}"
        ;;
    *)
        echo "GPT-Researcher Service Manager"
        echo ""
        echo "Usage: $0 {init|start|stop|restart|status}"
        echo ""
        echo "Commands:"
        echo "  init    - Create venv and install Python + JS dependencies"
        echo "  start   - Activate venv and start backend + frontend"
        echo "  stop    - Stop all services and deactivate venv"
        echo "  restart - Stop and restart services (stays in venv)"
        echo "  status  - Check if services are running"
        echo ""
        echo "Environment variables:"
        echo "  BACKEND_PORT  - Backend port (default: 8000)"
        echo "  FRONTEND_PORT - Frontend port (default: 3000)"
        exit 1
        ;;
esac
