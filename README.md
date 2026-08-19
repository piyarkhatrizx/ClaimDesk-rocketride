# ClaimDesk

ClaimDesk is an AI-assisted insurance claim intake and analysis application built with **RocketRide**.

Users can upload vehicle damage photos and an accident description, then ClaimDesk runs the evidence through a RocketRide pipeline, analyzes the damage with a local vision model, cross-checks the written description against the visual findings, and generates a structured claim report for an adjuster.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Limitations](#limitations)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)

## Features

- AI-based vehicle damage analysis
- Damage severity and damaged-part detection
- Description vs. image contradiction checking
- Deterministic claim triage: **Fast Track, Standard, High Priority**
- Safety and discrepancy flags
- Guardrails: prompt-injection, PII, and JSON-format validation on the analysis output
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
NER + Anonymization
   │
   ▼
Claim Analysis Prompt (Llama 3.1 8B)
   │
   ▼
Guardrails
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
- **Llama 3.1 8B** — claim analysis, sentiment scoring, and the adjuster assistant
- **RocketRide Guardrails** — prompt-injection, PII, and output-format validation
- **HTML / CSS / JavaScript** — frontend
- **Pillow / pillow-heif** — image handling and metadata removal

## Limitations

ClaimDesk relies on local, CPU-run models for all its functions, sacrificing accuracy and speed for user privacy. The vision model has occasionally misjudged the extent of vehicle damage, recognizing damage on vehicles with no visible damage or failing to identify damage in a photo. The analysis model has, on occasion, responded with conversational text instead of the required JSON report; in these instances, the claim is flagged as "Needs Manual Review". Because ClaimDesk maintains a single instance of the claim analysis model during the app's lifetime, one claim's analysis can theoretically influence another; this can be avoided by restarting ./run.sh. Finally, claims take 30 seconds to a few minutes to process depending on the machine's processing power, and each claim has a 30-second vision model timeout that can result in failures on slow machines.

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

The vision model is configurable via `ROCKETRIDE_VISION_MODEL` in `.env` (see below) -- whichever model you set there must be pulled locally (`ollama pull <model>`) before starting.

### Run

```bash
git clone <https://github.com/piyarkhatrizx/ClaimDesk-rocketride.git>
cd claimdesk-rocketride

cp .env.example .env

python3 -m venv .venv
source .venv/bin/activate

chmod +x run.sh
./run.sh
```

`.env` is gitignored and not created automatically -- copy it from `.env.example` before your first run, or `ClaimDesk.py` and the pipeline won't have `ROCKETRIDE_APIKEY` / `ROCKETRIDE_VISION_MODEL` to work with.

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
│   └── Claim_Process.pipe
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── .env.example
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
