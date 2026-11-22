import argparse
import hashlib
import secrets
from datetime import datetime, timezone

from .database import SessionLocal
from .models import Facility, FacilityAccessKey


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Issue or revoke a facility-scoped MediReach API key."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--facility-id", type=int, help="Issue a key for this active facility")
    group.add_argument("--revoke-key-id", type=int, help="Revoke an existing access-key record")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.revoke_key_id is not None:
            access_key = db.get(FacilityAccessKey, args.revoke_key_id)
            if access_key is None:
                raise SystemExit("Access key not found")
            if access_key.revoked_at is None:
                access_key.revoked_at = datetime.now(timezone.utc)
                db.commit()
            print(f"Facility access key {access_key.id} is revoked.")
            return

        facility = db.get(Facility, args.facility_id)
        if facility is None or not facility.is_active:
            raise SystemExit("Active facility not found")

        raw_key = secrets.token_urlsafe(32)
        access_key = FacilityAccessKey(
            facility_id=facility.id,
            key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
        )
        db.add(access_key)
        db.commit()
        db.refresh(access_key)
        print(f"Facility: {facility.name} (ID {facility.id})")
        print(f"Access key record ID: {access_key.id}")
        print("Copy this key now; the plaintext value is not stored and cannot be shown again:")
        print(raw_key)
    finally:
        db.close()


if __name__ == "__main__":
    main()
