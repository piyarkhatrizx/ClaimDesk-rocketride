"""
VoiceFlow Client
Send audio files or text commands to the VoiceFlow pipeline.
"""

import asyncio
import sys
import os

try:
    from rocketride import RocketRideClient
except ImportError:
    print("Install the SDK: pip install rocketride")
    sys.exit(1)

URI = "http://localhost:5565"


async def send_audio(filepath: str):
    """Send an audio file through the full pipeline."""
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    with open(filepath, "rb") as f:
        audio_data = f.read()

    filename = os.path.basename(filepath)
    mime = "audio/wav" if filename.endswith(".wav") else "audio/mpeg"

    async with RocketRideClient(uri=URI) as client:
        result = await client.use(filepath="pipelines/voiceflow.pipe")
        token = result["token"]

        print(f"Sending: {filename}")
        response = await client.send(token, audio_data, {"name": filename}, mime)
        print(f"VoiceFlow: {response}")

        await client.terminate(token)


async def send_text(text: str):
    """Send raw text to test intent classification without audio."""
    async with RocketRideClient(uri=URI) as client:
        result = await client.use(filepath="pipelines/voiceflow.pipe")
        token = result["token"]

        print(f"Sending: {text}")
        response = await client.send(token, text, {"name": "text-input"}, "text/plain")
        print(f"VoiceFlow: {response}")

        await client.terminate(token)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python client.py recording.wav")
        print("  python client.py --text 'search for AI news'")
        sys.exit(1)

    if sys.argv[1] == "--text":
        asyncio.run(send_text(" ".join(sys.argv[2:])))
    else:
        asyncio.run(send_audio(sys.argv[1]))