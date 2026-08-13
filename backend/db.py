import os
import re
import asyncio
from datetime import datetime, timedelta

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row


# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL", "")

    if not url:
        raise ValueError(
            "DATABASE_URL environment variable is not set"
        )

    return url


def _parse_dur_mins(duration: int | str) -> int:
    if isinstance(duration, int):
        return duration

    match = re.search(r"(\d+)", str(duration))

    if match:
        val = int(match.group(1))

        if "h" in str(duration).lower():
            return val * 60

        return val

    return 30


# --------------------------------------------------
# Database helper
# --------------------------------------------------

def _connect():
    """
    Create a normal synchronous PostgreSQL connection.

    We use this instead of psycopg.AsyncConnection because
    Windows + Uvicorn can use the ProactorEventLoop, which
    psycopg async connections do not support.
    """
    return psycopg.connect(
        get_db_url(),
        row_factory=dict_row,
    )


# --------------------------------------------------
# Initialize database
# --------------------------------------------------

async def init_db():
    def _init():
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS appointments (
                    id SERIAL PRIMARY KEY,
                    cal_booking_uid TEXT,
                    caller_name TEXT NOT NULL,
                    reason TEXT,
                    date_time TEXT NOT NULL,
                    contact_number TEXT,
                    email TEXT,
                    status TEXT DEFAULT 'confirmed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                """
                ALTER TABLE appointments
                ADD COLUMN IF NOT EXISTS email TEXT;
                """
            )

            conn.execute(
                """
                ALTER TABLE appointments
                ADD COLUMN IF NOT EXISTS duration INT DEFAULT 30;
                """
            )

            conn.commit()

    await asyncio.to_thread(_init)


# --------------------------------------------------
# Save booking
# --------------------------------------------------

async def save_booking(
    caller_name: str,
    reason: str,
    date_time: str,
    contact_number: str,
    cal_booking_uid: str | None = None,
    email: str = "",
    duration: int | str = 30,
) -> int:

    dur_mins = _parse_dur_mins(duration)

    def _save():
        with _connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO appointments
                (
                    cal_booking_uid,
                    caller_name,
                    reason,
                    date_time,
                    contact_number,
                    email,
                    duration
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    cal_booking_uid,
                    caller_name,
                    reason,
                    date_time,
                    contact_number,
                    email,
                    dur_mins,
                ),
            )

            row = cur.fetchone()
            conn.commit()

            return row["id"]

    return await asyncio.to_thread(_save)


# --------------------------------------------------
# Check slot availability
# --------------------------------------------------

async def check_slot_available(
    date_time: str,
    exclude_booking_id: int | None = None,
    duration: int | str = 30,
) -> bool:

    new_dur = _parse_dur_mins(duration)

    try:
        new_start = datetime.strptime(
            date_time,
            "%Y-%m-%d %H:%M",
        )
    except Exception:
        return False

    new_end = new_start + timedelta(minutes=new_dur)

    date_prefix = date_time[:10]

    def _check():

        with _connect() as conn:

            if exclude_booking_id is not None:

                cur = conn.execute(
                    """
                    SELECT
                        date_time,
                        COALESCE(duration, 30) AS duration
                    FROM appointments
                    WHERE date_time LIKE %s
                    AND status = 'confirmed'
                    AND id != %s
                    """,
                    (
                        f"{date_prefix}%",
                        exclude_booking_id,
                    ),
                )

            else:

                cur = conn.execute(
                    """
                    SELECT
                        date_time,
                        COALESCE(duration, 30) AS duration
                    FROM appointments
                    WHERE date_time LIKE %s
                    AND status = 'confirmed'
                    """,
                    (
                        f"{date_prefix}%",
                    ),
                )

            rows = cur.fetchall()

        for row in rows:

            dt_str = row["date_time"]
            ex_dur = row["duration"]

            try:

                ex_start = datetime.strptime(
                    dt_str,
                    "%Y-%m-%d %H:%M",
                )

                ex_end = ex_start + timedelta(
                    minutes=int(ex_dur)
                )

                if new_start < ex_end and ex_start < new_end:
                    return False

            except Exception:
                continue

        return True

    return await asyncio.to_thread(_check)


# --------------------------------------------------
# Get available slots
# --------------------------------------------------

async def get_available_slots(
    date: str,
    duration: int | str = 30,
) -> list[str]:

    dur_mins = _parse_dur_mins(duration)

    all_slots = []

    # 9:00 AM - 5:00 PM
    for h in range(9, 17):

        all_slots.append(
            f"{date} {h:02d}:00"
        )

        all_slots.append(
            f"{date} {h:02d}:30"
        )

    available = []

    for slot in all_slots:

        if await check_slot_available(
            slot,
            duration=dur_mins,
        ):
            available.append(slot)

    return available


# --------------------------------------------------
# Get booking
# --------------------------------------------------

async def get_booking(
    booking_id: int,
) -> dict | None:

    def _get():

        with _connect() as conn:

            cur = conn.execute(
                """
                SELECT *
                FROM appointments
                WHERE id = %s
                """,
                (booking_id,),
            )

            row = cur.fetchone()

            return dict(row) if row else None

    return await asyncio.to_thread(_get)


# --------------------------------------------------
# Cancel booking
# --------------------------------------------------

async def cancel_booking(
    booking_id: int,
) -> bool:

    def _cancel():

        with _connect() as conn:

            cur = conn.execute(
                """
                UPDATE appointments
                SET status = 'cancelled'
                WHERE id = %s
                AND status = 'confirmed'
                """,
                (booking_id,),
            )

            conn.commit()

            return cur.rowcount > 0

    return await asyncio.to_thread(_cancel)


# --------------------------------------------------
# Reschedule booking
# --------------------------------------------------

async def reschedule_booking(
    booking_id: int,
    new_date_time: str,
) -> bool:

    if not await check_slot_available(
        new_date_time,
        exclude_booking_id=booking_id,
    ):
        return False

    def _reschedule():

        with _connect() as conn:

            cur = conn.execute(
                """
                UPDATE appointments
                SET date_time = %s
                WHERE id = %s
                AND status = 'confirmed'
                """,
                (
                    new_date_time,
                    booking_id,
                ),
            )

            conn.commit()

            return cur.rowcount > 0

    return await asyncio.to_thread(_reschedule)


# --------------------------------------------------
# Get all bookings
# --------------------------------------------------

async def get_all_bookings() -> list[dict]:

    def _get_all():

        with _connect() as conn:

            cur = conn.execute(
                """
                SELECT *
                FROM appointments
                ORDER BY created_at DESC
                """
            )

            rows = cur.fetchall()

            return [dict(row) for row in rows]

    return await asyncio.to_thread(_get_all)


# --------------------------------------------------
# Lookup booking
# --------------------------------------------------

async def lookup_booking(
    query: str,
) -> list[dict]:

    clean_q = query.strip()
    q_like = f"%{clean_q.lower()}%"

    def _lookup():

        with _connect() as conn:

            if clean_q.isdigit():

                cur = conn.execute(
                    """
                    SELECT *
                    FROM appointments
                    WHERE id = %s
                    OR contact_number LIKE %s
                    ORDER BY id DESC
                    LIMIT 5
                    """,
                    (
                        int(clean_q),
                        q_like,
                    ),
                )

            else:

                cur = conn.execute(
                    """
                    SELECT *
                    FROM appointments
                    WHERE LOWER(caller_name) LIKE %s
                    OR contact_number LIKE %s
                    OR LOWER(email) LIKE %s
                    ORDER BY id DESC
                    LIMIT 5
                    """,
                    (
                        q_like,
                        q_like,
                        q_like,
                    ),
                )

            rows = cur.fetchall()

            return [dict(row) for row in rows]

    return await asyncio.to_thread(_lookup)