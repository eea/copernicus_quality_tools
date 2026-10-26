"""A stable required check must reject failed, cancelled and skipped CI jobs."""

import json
import os


def unsuccessful_jobs(jobs):
    if not jobs:
        return ["No prerequisite jobs were reported"]
    return [name for name, job in jobs.items() if job.get("result") != "success"]


def main():
    failures = unsuccessful_jobs(json.loads(os.environ["CI_JOB_RESULTS"]))
    if failures:
        raise SystemExit("CI prerequisites did not all succeed: " + ", ".join(failures))
    print("All required QC Tool checks passed.")


if __name__ == "__main__":
    main()
