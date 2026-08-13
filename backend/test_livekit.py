import os
import asyncio

from dotenv import load_dotenv
from livekit.api import LiveKitAPI
from livekit.protocol.room import ListRoomsRequest


# Load backend/.env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Windows + Psycopg/async compatibility
if os.name == "nt":
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )


async def main():
    url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not url:
        print("ERROR: LIVEKIT_URL is missing")
        return

    if not api_key:
        print("ERROR: LIVEKIT_API_KEY is missing")
        return

    if not api_secret:
        print("ERROR: LIVEKIT_API_SECRET is missing")
        return

    print("Connecting to LiveKit...")

    api = LiveKitAPI(
        url=url,
        api_key=api_key,
        api_secret=api_secret,
    )

    try:
        response = await api.room.list_rooms(
            ListRoomsRequest()
        )

        print("LIVEKIT CONNECTION SUCCESSFUL")
        print(f"Existing rooms: {len(response.rooms)}")

    except Exception as e:
        print("LIVEKIT CONNECTION FAILED")
        print(type(e).__name__)
        print(str(e))

    finally:
        await api.aclose()


if __name__ == "__main__":
    asyncio.run(main())