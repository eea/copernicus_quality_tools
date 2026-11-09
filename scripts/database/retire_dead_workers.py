import argparse
import json
import os
import subprocess

from kubectl_files import find_pod


# Instructions: Workers register with the maintenance service by pod IP, and
# registrations are removed only by an explicit retirement. After worker pods
# restart, the stale IPs make maintenance mode wait for workers that no longer
# exist. This script retires every registered worker whose IP does not belong to
# a running worker pod, using the 'maintenance retire-worker' command of the
# frontend pod, and then optionally re-checks readiness.
# Prerequisities:
# - kubectl installed and configured to access the Kubernetes cluster
# - Access to the QC Tool frontend and worker pods
#
# Retiring is your attestation that nothing runs on the retired address, and any
# job still 'running' on it is marked as errored. The pod list is the evidence:
# the script refuses to run when it finds no running worker pod.


# ================= CONFIGURATION =================
NAMESPACE = os.getenv("K8S_NAMESPACE", "qc-tool")
POD_NAME = os.getenv("K8S_POD_NAME", "")  # Empty: first running pod with POD_PREFIX.
POD_PREFIX = os.getenv("K8S_POD_PREFIX", "qc-tool-copernicus-qc-tool-frontend")
WORKER_POD_PREFIX = os.getenv("K8S_WORKER_POD_PREFIX", "qc-tool-copernicus-qc-tool-worker")
# =================================================

MANAGE = "python3 -m qc_tool.frontend.manage maintenance"


def kubectl_exec(pod, shell_command):
    return ["kubectl", "exec", "-n", NAMESPACE, pod, "--", "sh", "-c", shell_command]


def live_worker_ips():
    """IPs of the running worker pods that are not being deleted."""
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", NAMESPACE, "--field-selector=status.phase=Running", "-o", "json"],
        stdout=subprocess.PIPE, text=True, check=True,
    )
    ips = set()
    for item in json.loads(result.stdout)["items"]:
        if (item["metadata"]["name"].startswith(WORKER_POD_PREFIX)
                and not item["metadata"].get("deletionTimestamp")
                and item["status"].get("podIP")):
            ips.add(item["status"]["podIP"])
    return ips


def maintenance(pod, *options):
    """Run a maintenance command in the pod and return the JSON state it prints."""
    result = subprocess.run(
        kubectl_exec(pod, " ".join([MANAGE, *options])),
        stdout=subprocess.PIPE, text=True,
    )
    start = result.stdout.find("{")
    state = json.JSONDecoder().raw_decode(result.stdout[start:])[0] if start >= 0 else None
    return result.returncode, state


def worker_host(url):
    return url.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Only list the registered workers that would be retired.")
    parser.add_argument("--check", action="store_true",
                        help="After retiring, run 'maintenance check' to re-check readiness.")
    args = parser.parse_args()

    try:
        subprocess.run(["kubectl", "version", "--client"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'kubectl' command not found. Ensure kubectl is installed and in your PATH.")
        return

    live = live_worker_ips()
    if not live:
        raise SystemExit(f"Error: no running pod starting with '{WORKER_POD_PREFIX}' in namespace '{NAMESPACE}'; "
                         "refusing to retire every worker.")
    print(f"Running worker pods: {', '.join(sorted(live))}", flush=True)

    pod = find_pod(NAMESPACE, POD_NAME, POD_PREFIX)
    code, state = maintenance(pod, "status")
    if code != 0 or state is None:
        raise SystemExit(f"Error: reading the maintenance status in {NAMESPACE}/{pod} failed.")
    stale = [url for url in state["workers"] if worker_host(url) not in live]
    missing = sorted(live - {worker_host(url) for url in state["workers"]})
    print(f"{len(state['workers'])} registered workers, {len(stale)} not running.", flush=True)
    if missing:
        print(f"Running but not registered (they register when they start a claim): {', '.join(missing)}")

    if args.dry_run:
        for url in stale:
            print(f" Would retire {url}")
        print("Nothing retired.")
        return

    for url in stale:
        # Every retirement increments the generation, which the next one must pass.
        code, retired = maintenance(pod, "retire-worker", f"--worker-url {url}",
                                    f"--generation {state['generation']}", "--verified-stopped")
        if code != 0 or retired is None:
            raise SystemExit(f"Error: retiring {url} failed (exit code {code}); see the output above.")
        state = retired
        print(f" Retired {url}", flush=True)

    if args.check:
        if not state["enabled"]:
            print("Maintenance is off; nothing to check.")
        else:
            code, state = maintenance(pod, "check")
            print(f"Readiness: phase={state['phase'] if state else '?'}"
                  + "".join(f"\n  {blocker}" for blocker in (state or {}).get("blockers", [])))
    print("Done!")


if __name__ == "__main__":
    main()
