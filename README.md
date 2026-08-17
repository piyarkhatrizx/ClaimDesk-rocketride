# ClaimDesk

ClaimDesk is an AI-assisted insurance claim intake and analysis application built with **RocketRide**.

Users can upload vehicle damage photos and an accident description, then ClaimDesk runs the evidence through a RocketRide pipeline, analyzes the damage with a local vision model, cross-checks the written description against the visual findings, and generates a structured claim report for an adjuster.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)

## Features

- AI-based vehicle damage analysis
- Damage severity and damaged-part detection
- Description vs. image contradiction checking
- Deterministic claim triage: **Fast Track, Standard, High Priority**
- Safety and discrepancy flags
- Adjuster AI assistant using Ollama
- EXIF metadata removal from uploaded images
- Claim history
- PDF report export
- Automatic RocketRide engine and webhook discovery
- One-command startup and clean shutdown

## Architecture

```text
Browser
   │
   ▼
serve.py
   │
   ├── Claim validation / triage
   ├── Description cross-checking
   ├── Ollama adjuster chat
   │
   ▼
RocketRide Webhook
   │
   ▼
Claim_Process.pipe
   │
   ▼
LLaVA Vision Analysis
   │
   ▼
Structured Claim Report
```

ClaimDesk automatically discovers RocketRide's dynamically assigned local engine and webhook ports, so no manual port configuration is required.

## Tech Stack

- **RocketRide** — AI pipeline orchestration
- **Python** — backend and local server
- **Ollama** — local AI runtime
- **LLaVA** — vehicle damage image analysis
- **Llama 3.1 8B** — adjuster assistant
- **HTML / CSS / JavaScript** — frontend
- **Pillow / pillow-heif** — image handling and metadata removal

## Quick Start

### Requirements

- macOS
- Python 3.10+
- RocketRide local engine
- Ollama

Required Ollama models:

```text
llava:latest
llama3.1:8b
```

### Run

```bash
git clone <repository-url>
cd claimdesk-rocketride

python3 -m venv .venv
source .venv/bin/activate

chmod +x run.sh
./run.sh
```

Make sure RocketRide is connected locally in VS Code before starting.

ClaimDesk will open at:

```text
http://127.0.0.1:8000
```

Press `Ctrl+C` to stop the web server, pipeline launcher, and active RocketRide tasks.

## Project Structure

```text
claimdesk-rocketride/
├── pipelines/
│   ├── Claim_Process.pipe
│   └── Claim_Chat.pipe
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── ClaimDesk.py
├── serve.py
├── run.sh
├── requirements.txt
└── README.md
```

`ClaimDesk.py` starts the RocketRide pipeline and discovers the local engine.

`serve.py` serves the frontend, forwards claims to RocketRide, runs rule-based auditing, removes image metadata, and powers the adjuster assistant.

`run.sh` checks dependencies and models, starts ClaimDesk, opens the browser, and cleans up active tasks on exit.

---

Built as a real-world demonstration of combining **multimodal AI, deterministic validation, local inference, and RocketRide pipeline orchestration** into a usable insurance workflow.
