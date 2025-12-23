#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES=("fandomat-vision" "fandomat-plc")
SERVICE_USER="radxa"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_prerequisites() {
    log_info "Checking prerequisites..."

    if [[ ! -d "$SCRIPT_DIR/.venv" ]]; then
        log_error "Virtual environment not found at $SCRIPT_DIR/.venv"
        log_info "Create it with: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi

    if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
        log_warn ".env file not found. Services may fail to start properly."
        log_info "Copy .env.example to .env and configure it."
    fi

    if ! groups "$SERVICE_USER" | grep -q dialout; then
        log_warn "User $SERVICE_USER is not in 'dialout' group. PLC communication may fail."
        log_info "Add user to group: sudo usermod -aG dialout $SERVICE_USER"
    fi

    if ! groups "$SERVICE_USER" | grep -q video; then
        log_warn "User $SERVICE_USER is not in 'video' group. Camera access may fail."
        log_info "Add user to group: sudo usermod -aG video $SERVICE_USER"
    fi
}

install_services() {
    log_info "Installing systemd services..."

    for svc in "${SERVICES[@]}"; do
        if [[ ! -f "$SCRIPT_DIR/${svc}.service" ]]; then
            log_error "Service file not found: ${svc}.service"
            exit 1
        fi
        sudo install -m 0644 "$SCRIPT_DIR/${svc}.service" "/etc/systemd/system/${svc}.service"
        log_info "Installed ${svc}.service"
    done

    sudo systemctl daemon-reload
    log_info "Systemd daemon reloaded"
}

enable_services() {
    log_info "Enabling services..."
    for svc in "${SERVICES[@]}"; do
        sudo systemctl enable "${svc}.service"
    done
}

start_services() {
    log_info "Starting services..."
    for svc in "${SERVICES[@]}"; do
        sudo systemctl start "${svc}.service"
        sleep 1
    done
}

stop_services() {
    log_info "Stopping services..."
    for svc in "${SERVICES[@]}"; do
        sudo systemctl stop "${svc}.service" 2>/dev/null || true
    done
}

uninstall_services() {
    log_info "Uninstalling services..."

    stop_services

    for svc in "${SERVICES[@]}"; do
        sudo systemctl disable "${svc}.service" 2>/dev/null || true
        sudo rm -f "/etc/systemd/system/${svc}.service"
        log_info "Removed ${svc}.service"
    done

    sudo systemctl daemon-reload
    log_info "Services uninstalled"
}

show_status() {
    echo ""
    log_info "Service status:"
    echo "----------------------------------------"
    for svc in "${SERVICES[@]}"; do
        status=$(systemctl is-active "${svc}.service" 2>/dev/null || echo "inactive")
        enabled=$(systemctl is-enabled "${svc}.service" 2>/dev/null || echo "disabled")
        if [[ "$status" == "active" ]]; then
            echo -e "${GREEN}${svc}${NC}: $status ($enabled)"
        else
            echo -e "${RED}${svc}${NC}: $status ($enabled)"
        fi
    done
    echo "----------------------------------------"
    echo ""
    log_info "View logs: journalctl -u fandomat-plc -u fandomat-vision -f"
}

usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  install   - Install and enable services (default)"
    echo "  start     - Start services"
    echo "  stop      - Stop services"
    echo "  restart   - Restart services"
    echo "  status    - Show service status"
    echo "  uninstall - Stop, disable and remove services"
    echo "  logs      - Follow service logs"
}

case "${1:-install}" in
    install)
        check_prerequisites
        install_services
        enable_services
        start_services
        show_status
        ;;
    start)
        start_services
        show_status
        ;;
    stop)
        stop_services
        show_status
        ;;
    restart)
        stop_services
        start_services
        show_status
        ;;
    status)
        show_status
        ;;
    uninstall)
        uninstall_services
        ;;
    logs)
        journalctl -u fandomat-plc -u fandomat-vision -f
        ;;
    *)
        usage
        exit 1
        ;;
esac
