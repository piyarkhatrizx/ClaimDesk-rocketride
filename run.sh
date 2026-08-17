#!/bin/bash

set -e

cd "$(dirname "$0")"

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

# ---- START ROCKETRIDE PIPELINE ----
rm -f .rocketride_token .rocketride_uri
echo ""
echo "Starting RocketRide pipeline..."

python3 ClaimDesk.py > claimdesk.log 2>&1 &
PIPELINE_PID=$!

echo "Pipeline launcher PID: $PIPELINE_PID"

# Give it time to connect/start
sleep 3

# Make sure claimdesk.py did not crash
if ! kill -0 "$PIPELINE_PID" 2>/dev/null; then
    echo ""
    echo "RocketRide pipeline failed to start."
    echo ""
    cat claimdesk.log
    exit 1
fi

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