import asyncio
import subprocess
import re
import glob

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
            ["lsof", "-Pan", "-p", pid, "-iTCP", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            match = re.search(r"127\.0\.0\.1:(\d+)\s+\(LISTEN\)", line)
            if match:
                port = int(match.group(1))
                if 50000 <= port <= 65535:
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
            # DAP login uses ROCKETRIDE_APIKEY (the SDK's documented auth
            # credential, read automatically from .env/the environment when
            # `auth` is omitted). The webhook node's "Private Token" is a
            # different secret entirely -- it authenticates HTTP calls to a
            # running pipeline's /webhook endpoint, not the engine login, and
            # the engine rejects it here with a 400 rather than a clean 401.
            async with RocketRideClient(uri=uri) as client:

                res = await client.use(
                    filepath="./pipelines/Claim_Process.pipe"
                )

                token = res["token"]
                public_token = res.get("publicToken", "")

                print(f"Connected to RocketRide on port {port}")
                print("Started:", token)

                with open(".rocketride_token", "w") as f:
                    f.write(token)

                with open(".rocketride_uri", "w") as f:
                    f.write(uri)

                with open(".rocketride_port", "w") as f:
                    f.write(str(port))

                if public_token:
                    with open(".rocketride_auth", "w") as f:
                        f.write(public_token)
                    print(f"Webhook auth: {public_token[:12]}...")

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