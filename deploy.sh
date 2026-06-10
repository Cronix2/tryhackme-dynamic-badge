#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Build, (re)deploy and restart the tryhackme-dynamic-badge service
#
# Usage (non-interactive):
#   ./deploy.sh [OPTIONS]
#
#   Options:
#     -u, --username <name>   TryHackMe username                  (required)
#     -p, --port     <port>   Host port to bind                   [default: 8000]
#     -t, --tag      <tag>    Docker image tag                    [default: tryhackme-badge]
#     -c, --cache    <path>   Host path for the persistent cache  [default: ./cache]
#     -e, --env-file <path>   Path to a .env file to load        [default: .env if present]
#         --no-cache          Force Docker build without layer cache
#     -h, --help              Show this help and exit
#
# Usage (interactive — no arguments):
#   ./deploy.sh
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
_bold="\033[1m"
_green="\033[0;32m"
_yellow="\033[0;33m"
_red="\033[0;31m"
_cyan="\033[0;36m"
_reset="\033[0m"

info()    { echo -e "${_cyan}[INFO]${_reset}  $*"; }
success() { echo -e "${_green}[OK]${_reset}    $*"; }
warn()    { echo -e "${_yellow}[WARN]${_reset}  $*"; }
error()   { echo -e "${_red}[ERROR]${_reset} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Default values ────────────────────────────────────────────────────────────
IMAGE_TAG="tryhackme-badge"
HOST_PORT="8000"
CACHE_DIR="$(pwd)/cache"
ENV_FILE=""
NO_CACHE_FLAG=""
THM_USERNAME=""
CONTAINER_NAME="tryhackme-badge"

# ── Help ──────────────────────────────────────────────────────────────────────
usage() {
    grep '^#' "$0" | grep -v '#!/' | sed 's/^# \{0,1\}//'
    exit 0
}

# ── Argument parser ───────────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -u|--username)  THM_USERNAME="${2:?--username requires a value}"; shift 2 ;;
            -p|--port)      HOST_PORT="${2:?--port requires a value}"; shift 2 ;;
            -t|--tag)       IMAGE_TAG="${2:?--tag requires a value}"; shift 2 ;;
            -c|--cache)     CACHE_DIR="${2:?--cache requires a value}"; shift 2 ;;
            -e|--env-file)  ENV_FILE="${2:?--env-file requires a value}"; shift 2 ;;
            --no-cache)     NO_CACHE_FLAG="--no-cache"; shift ;;
            -h|--help)      usage ;;
            *) die "Unknown option: $1 (run with --help for usage)" ;;
        esac
    done
}

# ── Interactive mode ──────────────────────────────────────────────────────────
interactive_mode() {
    echo -e "${_bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${_reset}"
    echo -e "${_bold}  TryHackMe Dynamic Badge — Interactive Deploy${_reset}"
    echo -e "${_bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${_reset}"
    echo ""

    # Load .env defaults so they appear as pre-filled suggestions
    local env_username=""
    if [[ -f ".env" ]]; then
        env_username=$(grep -E '^THM_USERNAME=' .env 2>/dev/null | cut -d= -f2 | tr -d '"' || true)
        ENV_FILE=".env"
    fi

    # Username
    local prompt_username="${env_username:-your_username}"
    read -rp "$(echo -e "  ${_bold}TryHackMe username${_reset} [${prompt_username}]: ")" input
    THM_USERNAME="${input:-$env_username}"
    [[ -z "$THM_USERNAME" ]] && die "Username is required."

    # Port
    read -rp "$(echo -e "  ${_bold}Host port${_reset} [${HOST_PORT}]: ")" input
    HOST_PORT="${input:-$HOST_PORT}"

    # Image tag
    read -rp "$(echo -e "  ${_bold}Docker image tag${_reset} [${IMAGE_TAG}]: ")" input
    IMAGE_TAG="${input:-$IMAGE_TAG}"

    # Cache directory
    read -rp "$(echo -e "  ${_bold}Cache directory${_reset} [${CACHE_DIR}]: ")" input
    CACHE_DIR="${input:-$CACHE_DIR}"

    # No-cache build?
    read -rp "$(echo -e "  ${_bold}Force rebuild without Docker cache?${_reset} [y/N]: ")" input
    [[ "${input,,}" == "y" ]] && NO_CACHE_FLAG="--no-cache"

    echo ""
}

# ── Core deploy logic ─────────────────────────────────────────────────────────
run_deploy() {
    # Validate
    [[ -z "$THM_USERNAME" ]] && die "THM_USERNAME is not set. Use -u/--username or run interactively."

    # Sanity-check Docker is available
    command -v docker &>/dev/null || die "Docker is not installed or not in PATH."

    # Resolve absolute cache path
    CACHE_DIR="$(realpath -m "$CACHE_DIR")"

    echo ""
    echo -e "${_bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${_reset}"
    echo -e "${_bold}  Deployment summary${_reset}"
    echo -e "${_bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${_reset}"
    echo -e "  Username   : ${_green}${THM_USERNAME}${_reset}"
    echo -e "  Image tag  : ${IMAGE_TAG}"
    echo -e "  Container  : ${CONTAINER_NAME}"
    echo -e "  Host port  : ${HOST_PORT}"
    echo -e "  Cache dir  : ${CACHE_DIR}"
    [[ -n "$ENV_FILE" ]] && echo -e "  .env file  : ${ENV_FILE}"
    [[ -n "$NO_CACHE_FLAG" ]] && echo -e "  Build cache: ${_yellow}disabled${_reset}"
    echo ""

    # ── 1. Build the Docker image ─────────────────────────────────────────
    info "Building Docker image '${IMAGE_TAG}'…"
    # shellcheck disable=SC2086
    docker build $NO_CACHE_FLAG -t "$IMAGE_TAG" .
    success "Image built."

    # ── 2. Stop & remove existing container (if any) ──────────────────────
    if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
        info "Stopping and removing existing container '${CONTAINER_NAME}'…"
        docker stop "$CONTAINER_NAME" &>/dev/null || true
        docker rm   "$CONTAINER_NAME" &>/dev/null || true
        success "Old container removed."
    fi

    # ── 3. Ensure cache directory exists on the host ──────────────────────
    mkdir -p "$CACHE_DIR"

    # ── 4. Build docker run arguments ─────────────────────────────────────
    RUN_ARGS=(
        --name "$CONTAINER_NAME"
        --restart unless-stopped
        -p "${HOST_PORT}:8000"
        -v "${CACHE_DIR}:/app/cache"
        -e "THM_USERNAME=${THM_USERNAME}"
    )

    # Forward every non-comment, non-empty line from the .env file
    if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
        while IFS= read -r line; do
            # skip comments and empty lines, and skip THM_USERNAME (already set)
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${line// }" ]] && continue
            [[ "$line" =~ ^THM_USERNAME= ]] && continue
            RUN_ARGS+=(-e "$line")
        done < "$ENV_FILE"
    fi

    # ── 5. Start the new container ────────────────────────────────────────
    info "Starting container '${CONTAINER_NAME}'…"
    docker run -d "${RUN_ARGS[@]}" "$IMAGE_TAG"
    success "Container started."

    # ── 6. Health check ───────────────────────────────────────────────────
    info "Waiting for service to become healthy…"
    local attempts=0
    local max=15
    until curl -sf "http://localhost:${HOST_PORT}/health" &>/dev/null; do
        attempts=$(( attempts + 1 ))
        if [[ $attempts -ge $max ]]; then
            warn "Health check did not pass after ${max} attempts."
            warn "Check container logs: docker logs ${CONTAINER_NAME}"
            break
        fi
        sleep 2
    done

    if curl -sf "http://localhost:${HOST_PORT}/health" &>/dev/null; then
        success "Service is up at http://localhost:${HOST_PORT}"
        success "Badge URL : http://localhost:${HOST_PORT}/badge.png"
    fi

    echo ""
}

# ── Entry point ───────────────────────────────────────────────────────────────
main() {
    if [[ $# -eq 0 ]]; then
        interactive_mode
    else
        parse_args "$@"
    fi
    run_deploy
}

main "$@"
