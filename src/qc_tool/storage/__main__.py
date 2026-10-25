"""Read-only startup check and explicit, isolated filesystem capability probe."""

import argparse
import sys

from .guard import StorageConfigurationError, check_storage, probe_storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "probe"))
    options = parser.parse_args()
    try:
        if options.action == "probe":
            probe_storage()
            print("Persistent storage filesystem probe passed. This checks this client only; "
                  "it does not certify multi-host locking or crash durability.")
        else:
            root = check_storage()
            print(f"Persistent storage is ready: {root}")
    except StorageConfigurationError as error:
        print(f"Persistent storage is not ready: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
