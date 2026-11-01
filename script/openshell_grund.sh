#!/bin/sh
# Show how to start Grund inside an OpenShell sandbox.
# Does not create a sandbox. This machine has no openshell binary and no gateway.
set -eu

policy="openshell/grund.yaml"
if ! command -v openshell >/dev/null 2>&1; then
  echo "openshell is not on PATH. The deterministic server and the track-3 scorer do not use it."
  echo "When a gateway is up, the create line is:"
else
  echo "openshell is on PATH. A gateway has to be up before create. The line is:"
fi
echo "openshell sandbox create --name grund --policy ${policy} -- python3 -m uvicorn grund.api:app --host 0.0.0.0 --port 8741"
echo "Model calls from inside the sandbox go to https://inference.local. The proxy adds the credential."
