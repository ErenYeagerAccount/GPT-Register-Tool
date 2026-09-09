"""Standalone UPI payment-link extractor. Does not run registration."""
from paylink.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
