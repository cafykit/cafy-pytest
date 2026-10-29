#!/usr/bin/env bash
# Run SRv6 accounting AP against the latest (or specified) VXR bake topo + NetPilot.
set -euo pipefail

USER_ID="${USER_ID:-aasrai}"
CAFY_WORK="${CAFY_WORK:-/nobackup/${USER_ID}/cafyap}"
BAKE="${1:-$(ls -td "$CAFY_WORK"/work/archive/test_vxr_* 2>/dev/null | head -1)}"
TOP="${TOP:-$BAKE/F3_P200.json}"

if [[ ! -f "$TOP" ]]; then
  echo "ERROR: baked topo not found: $TOP"
  echo "Bake may still be running. Watch:"
  echo "  tail -f \"$BAKE/all.log\""
  exit 1
fi

export BASE="/nobackup/${USER_ID}/cafy-pytest"
export RCA_REPO="/nobackup/${USER_ID}/rca_base_agents"
export GIT_REPO="/auto/cafy/release/xr-dev/26.4.1.23I/cafykit"
export CAFYAP_REPO="$CAFY_WORK"
export PYTHONPATH="$BASE/.venv/lib/python3.11/site-packages:$BASE:$RCA_REPO:$GIT_REPO/lib:${PYTHONPATH:-}"
export NETPILOT_CLI_PATH=/auto/vxr/netpilot/netpilot
export NETPILOT_CAFY_NO_CACHE=1
export NETPILOT_SCRATCH_ROOT="/nobackup/${USER_ID}/netpilot-scratch"
export MPLCONFIGDIR="/nobackup/${USER_ID}/matplotlib-cache"
mkdir -p "$NETPILOT_SCRATCH_ROOT" "$MPLCONFIGDIR"

export INPUT="$CAFYAP_REPO/srv6/accounting/srv6_loc_int_egress_acc_ap_input_file.json"
export TOPO="$TOP"
# TestSRv6AccountingCliValidation does not exist in this AP; use sim sanity testcase:
export NODEID="srv6_loc_int_egress_acc_ap.py::TestSRv6AccountingTelemetryValidation::test_srv6_accounting_telemetry_validation"

echo "Bake archive: $BAKE"
echo "Topo:         $TOPO"
echo

cd "$CAFYAP_REPO/srv6/accounting"
source /auto/cafy/release/latest/exec/bin/activate

/auto/cafy/release/latest/exec/bin/python -m pytest \
  -s --no-email --disable-warnings -v \
  "$NODEID" --test-input-file "$INPUT" -T "$TOPO" \
  --netpilot-cafy-triage-enable
