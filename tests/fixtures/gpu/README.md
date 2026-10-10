These small, deterministic fixtures follow upstream CLI schemas. Device identities
and readings are synthetic; they are not measurements from hardware available in CI.

AMD: https://github.com/ROCm/amdsmi/blob/amd-staging/amdsmi_cli/amdsmi_commands.py
`list` emits gpu/bdf/uuid/partition_id; `metric --usage --mem-usage --json` emits
usage.gfx_activity and mem_usage.used_vram/total_vram. Current AMD CLI uses an
MB unit label after dividing byte counts by 1024**2; Tower preserves that meaning.

Intel discovery example:
https://github.com/intel/xpumanager/blob/master/doc/smi_user_guide.md
Current counter structure:
https://github.com/intel/xpumanager/blob/master/cli/src/comlet_statistics.cpp
Only device_level values are taken as whole-device utilization. Tile-only values
and avg/min/max statistics do not substitute for a current device measurement.
