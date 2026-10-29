#!/usr/bin/env bash
# VXR sim bake (multicluster) + SRv6 accounting AP prep for aasrai on sjc-ads-5127.
# Phase 1: bake sim topo via test_vxr.py
# Phase 2: run accounting AP against baked topo (with NetPilot optional)
set -euo pipefail

USER_ID="${USER_ID:-aasrai}"
CAFY_WORK="${CAFY_WORK:-/nobackup/${USER_ID}/cafyap}"
# Use released cafykit — no /var/tmp/ios-xr clone required on ADS
KIT_REPO="${KIT_REPO:-/auto/cafy/release/xr-dev/26.4.1.23I/cafykit}"
CAFY_VENV="${CAFY_VENV:-/auto/cafy/release/latest/exec/bin/activate}"
SIM_SRC_HOST="${SIM_SRC_HOST:-ott-idt-exec1}"
SIM_SRC_DIR="${SIM_SRC_DIR:-/ws/asabouhi-ott/testbeds}"

mkdir -p "$CAFY_WORK/work"

echo "Copying sim inputs from ${SIM_SRC_HOST}:${SIM_SRC_DIR} ..."
scp "${SIM_SRC_HOST}:${SIM_SRC_DIR}/F3_200_2.json" \
    "$CAFY_WORK/work/F3_200_2_multicluster_retry.json"
scp "${SIM_SRC_HOST}:${SIM_SRC_DIR}/F3_200_2_bake_input.json" \
    "$CAFY_WORK/work/F3_200_2_bake_input_retry.json"

CAFY_WORK="$CAFY_WORK" python3 - <<'PY'
import json
import os

base = os.environ["CAFY_WORK"]

inp = os.path.join(base, "work/F3_200_2_bake_input_retry.json")
with open(inp) as f:
    data = json.load(f)
data["slurm_duration"] = 2
data.pop("simulation", None)
with open(inp, "w") as f:
    json.dump(data, f, indent=2)

topo = os.path.join(base, "work/F3_200_2_multicluster_retry.json")
with open(topo) as f:
    data = json.load(f)
slurm = data.setdefault("simulation", {}).setdefault("slurm_flags", {})
slurm.pop("node", None)
slurm["cluster"] = "multicluster"
slurm["partition"] = "regression"
slurm["hours"] = 2
slurm["pending_timeout"] = 10
with open(topo, "w") as f:
    json.dump(data, f, indent=2)

print("patched bake input:", inp)
print("patched topo:", topo)
print(json.dumps(slurm, indent=2))
PY

export CAFYAP_REPO="$CAFY_WORK"
export GIT_REPO="$KIT_REPO"
export PYTHONPATH="$GIT_REPO/lib:${PYTHONPATH:-}"
export PATH="/usr/cisco/bin:$PATH"

# NetPilot override (optional for bake; required for AP run)
export BASE="${BASE:-/nobackup/${USER_ID}/cafy-pytest}"
export RCA_REPO="${RCA_REPO:-/nobackup/${USER_ID}/rca_base_agents}"
export NETPILOT_CLI_PATH=/auto/vxr/netpilot/netpilot
export NETPILOT_CAFY_NO_CACHE=1
export NETPILOT_SCRATCH_ROOT="/nobackup/${USER_ID}/netpilot-scratch"
export MPLCONFIGDIR="/nobackup/${USER_ID}/matplotlib-cache"
mkdir -p "$NETPILOT_SCRATCH_ROOT" "$MPLCONFIGDIR"

cd "$KIT_REPO/test/hw/bake/vxr"
# shellcheck disable=SC1090
source "$CAFY_VENV"

echo
echo "Starting VXR bake (multicluster). In another terminal:"
echo "  BAKE=\$(ls -td ${CAFY_WORK}/work/archive/test_vxr_* | head -1)"
echo "  tail -f \"\$BAKE/all.log\""
echo

/auto/cafy/release/latest/exec/bin/python -m pytest test_vxr.py \
  --script-args="$CAFY_WORK/work/F3_200_2_bake_input_retry.json" \
  -T "$CAFY_WORK/work/F3_200_2_multicluster_retry.json" \
  --disable-warnings --no-email -v

BAKE=$(ls -td "$CAFY_WORK"/work/archive/test_vxr_* | head -1)
TOP="$BAKE/F3_P200.json"
echo
echo "Bake archive: $BAKE"
if [[ -f "$TOP" ]]; then
  echo "Baked topo:   $TOP"
  echo
  echo "Run accounting AP:"
  echo "  cd $CAFYAP_REPO/srv6/accounting"
  echo "  export PYTHONPATH=\"$BASE:$RCA_REPO:$GIT_REPO/lib:\${PYTHONPATH:-}\""
  echo "  export INPUT=\"$CAFYAP_REPO/srv6/accounting/srv6_loc_int_egress_acc_ap_input_file.json\""
  echo "  export TOPO=\"$TOP\""
  echo "  export NODEID=\"srv6_loc_int_egress_acc_ap.py::TestSRv6AccountingCliValidation::test_srv6_accounting_cli_validation\""
  echo "  /auto/cafy/release/latest/exec/bin/python -m pytest -s --no-email --disable-warnings -v \\"
  echo "    \"\$NODEID\" --test-input-file \"\$INPUT\" -T \"\$TOPO\" --netpilot-cafy-triage-enable"
else
  echo "WARNING: $TOP not found yet — check bake logs."
fi
