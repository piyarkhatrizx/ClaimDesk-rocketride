#!/bin/bash

set -e

cd "$(dirname "$0")"
# ---- PYTHON VERSION CHECK ----

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is not installed."
    echo "ClaimDesk requires Python 3.10 or newer."
    exit 1
fi

if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "ClaimDesk requires Python 3.10 or newer."
    echo "Current version: $(python3 --version)"
    exit 1
fi

echo "✓ $(python3 --version)"

# ---- PYTHON DEPENDENCIES ----

python3 -m pip install -r requirements.txt

# ---- PIPELINE PATCH ----

sed -i '' '/"reasoning_effort"/d' pipelines/Claim_Process.pipe

# ---- OLLAMA INSTALL CHECK ----

if ! command -v ollama >/dev/null 2>&1; then
    echo "Ollama is not installed."
    read -p "Would you like to download Ollama now? (y/n): " install_ollama

    if [[ "$install_ollama" =~ ^[Yy]$ ]]; then
        echo "Opening Ollama download page..."
        open "https://ollama.com/download"
        echo "Install Ollama, then run ./run.sh again."
        exit 0
    else
        echo "Ollama is required for the ClaimDesk AI pipeline."
        exit 1
    fi
fi

# ---- OLLAMA MODEL CHECK ----

required_models=("llava:latest" "llama3.1:8b")

for model in "${required_models[@]}"; do
    if ! ollama list | awk '{print $1}' | grep -qx "$model"; then
        echo ""
        echo "Required Ollama model '$model' is not installed."
        read -p "Would you like to download it now? (y/n): " install_model

        if [[ "$install_model" =~ ^[Yy]$ ]]; then
            echo "Downloading $model..."
            ollama pull "$model"
        else
            echo "Skipping $model."
            echo "Some ClaimDesk features may not work."
        fi
    else
        echo "✓ $model is installed."
    fi
done

# ---- LOAD ENV ----
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi
# ---- START ROCKETRIDE PIPELINE ----
rm -f .rocketride_token .rocketride_uri .rocketride_port .rocketride_auth
echo ""
echo "Starting RocketRide pipeline..."

python3 ClaimDesk.py > claimdesk.log 2>&1 &
PIPELINE_PID=$!

echo "Pipeline launcher PID: $PIPELINE_PID"

# Wait for ClaimDesk.py to actually finish connecting (it writes
# .rocketride_auth once client.use() succeeds) instead of guessing a fixed
# delay. Starting serve.py before this file exists is a real race: the web
# server comes up immediately and will forward requests with a stale/empty
# token, producing "Task token is required" on the very first submission.
echo "Waiting for RocketRide pipeline to connect..."
WAITED=0
while [ ! -f .rocketride_auth ]; do
    if ! kill -0 "$PIPELINE_PID" 2>/dev/null; then
        echo ""
        echo "RocketRide pipeline failed to start."
        echo ""
        cat claimdesk.log
        exit 1
    fi
    if [ "$WAITED" -ge 60 ]; then
        echo ""
        echo "RocketRide pipeline did not connect within 30s."
        echo ""
        cat claimdesk.log
        exit 1
    fi
    sleep 0.5
    WAITED=$((WAITED + 1))
done
echo "Pipeline connected."

# ---- CLEANUP ----

CLEANED_UP=0

cleanup() {
    if [ "$CLEANED_UP" -eq 1 ]; then
        return
    fi

    CLEANED_UP=1

    echo ""
    echo "Stopping ClaimDesk..."

    # Stop all RocketRide tasks on this local ClaimDesk engine
    if [ -f ".rocketride_uri" ]; then
        RR_URI=$(cat .rocketride_uri)

        TASK_TOKENS=$(rocketride list \
            --uri "$RR_URI" \
            --apikey YOUR_API_KEY \
            2>/dev/null |
            awk '/Token:/ {print $2}')

        for token in $TASK_TOKENS; do
            echo "Stopping RocketRide task $token..."

            rocketride stop \
                --uri "$RR_URI" \
                --apikey YOUR_API_KEY \
                --token "$token" \
                >/dev/null 2>&1 || true
        done
    fi

    # Stop claimdesk.py
    if kill -0 "$PIPELINE_PID" 2>/dev/null; then
        kill "$PIPELINE_PID" 2>/dev/null || true
        wait "$PIPELINE_PID" 2>/dev/null || true
    fi

    rm -f .rocketride_token .rocketride_uri

    echo "Everything stopped."
}

trap cleanup EXIT INT TERM
# ---- START WEB SERVER ----

echo ""
echo "Starting ClaimDesk web server..."
echo "Open: http://localhost:8000"
echo ""
# Open ClaimDesk automatically after the server starts
(
    sleep 2
    open http://127.0.0.1:8000
) &
python3 serve.py