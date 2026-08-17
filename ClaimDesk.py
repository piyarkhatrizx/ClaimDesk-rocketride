import asyncio
import subprocess
import re

from rocketride import RocketRideClient


def find_rocketride_ports():
    """
    Find localhost TCP ports being used by RocketRide engine processes.
    macOS only.
    """

    result = subprocess.run(
        ["pgrep", "-af", "RocketRide/engine/engine"],
        capture_output=True,
        text=True,
    )

    pids = []

    for line in result.stdout.strip().splitlines():
        match = re.match(r"(\d+)", line)

        if match:
            pids.append(match.group(1))

    ports = []

    for pid in pids:
        result = subprocess.run(
            [
                "lsof",
                "-Pan",
                "-p",
                pid,
                "-iTCP",
                "-sTCP:LISTEN",
            ],
            capture_output=True,
            text=True,
        )

        for line in result.stdout.splitlines():

            # Look specifically for IPv4 localhost listeners
            match = re.search(
                r"127\.0\.0\.1:(\d+)\s+\(LISTEN\)",
                line,
            )

            if match:
                port = int(match.group(1))

                # RocketRide --port=0 engines have been using
                # dynamic high-numbered ports on your Mac.
                if 50000 <= port <= 65000:
                    ports.append(port)

    return list(dict.fromkeys(ports))


async def start_pipeline():
    ports = find_rocketride_ports()

    if not ports:
        raise RuntimeError(
            "Could not find a local RocketRide engine.\n"
            "Make sure RocketRide is running in VS Code."
        )

    print("Found possible RocketRide ports:", ports)

    last_error = None

    for port in ports:
        uri = f"http://127.0.0.1:{port}"

        print(f"Trying {uri}...")

        try:
            async with RocketRideClient(
                uri=uri,
                auth="YOUR_API_KEY",
            ) as client:

                res = await client.use(
                    filepath="./pipelines/Claim_Process.pipe"
                )

                token = res["token"]

                print(f"Connected to RocketRide on port {port}")
                print("Started:", token)

                with open(".rocketride_token", "w") as f:
                    f.write(token)

                with open(".rocketride_uri", "w") as f:
                    f.write(uri)

                # Keep the pipeline alive
                await asyncio.Event().wait()

                return

        except Exception as e:
            last_error = e
            print(f"Port {port} did not work: {e}")

    raise RuntimeError(
        f"Found RocketRide ports, but none could start the pipeline.\n"
        f"Last error: {last_error}"
    )


if __name__ == "__main__":
    try:
        asyncio.run(start_pipeline())
    except KeyboardInterrupt:
        print("\nClaimDesk pipeline stopped.")