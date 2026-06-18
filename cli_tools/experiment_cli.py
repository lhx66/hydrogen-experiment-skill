#!/usr/bin/env python3
"""Orchestrate a hydrogen sensor experiment from one natural-language request."""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "hydrogen_experiment"
STATE_FILE = Path.home() / ".hydrogen_experiment_skill_state.json"
DEFAULT_MFC2_STABILIZE_TIME = 5
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from hydrogen_experiment import (  # noqa: E402
    DEFAULT_FBG_CHANNEL,
    DEFAULT_FBG_IP,
    DEFAULT_FBG_PORT,
    DEFAULT_MFC2_FLOW_SLM,
    DEFAULT_POWERMETER_RESOURCE,
    HIGH_CONCENTRATION_AUTH_LIMIT_PERCENT,
    calculate_h2_flow_sccm,
    parse_concentration_percent,
    parse_experiment_request_text,
    run_hydrogen_experiment,
)


def _json_print(payload: Dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def load_cli_state() -> Dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def save_cli_state(state: Dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_last_output_folder() -> Optional[str]:
    state = load_cli_state()
    output_folder = state.get("last_output_folder")
    return str(output_folder) if output_folder else None


def save_last_output_folder(output_folder: str) -> None:
    if not output_folder:
        return
    state = load_cli_state()
    state["last_output_folder"] = str(output_folder)
    save_cli_state(state)


def resolve_output_folder(output_folder: Optional[str]) -> str:
    if output_folder:
        save_last_output_folder(output_folder)
        return output_folder

    last_output_folder = load_last_output_folder()
    if last_output_folder:
        return last_output_folder

    raise ValueError("首次运行必须指定 --output-folder；之后未指定时会沿用上次实验数据文件夹")


def _build_steps(params: Dict, total_duration: int, mfc_port: str) -> List[Dict]:
    instrument = params["instrument"]
    h2_time = int(params["h2_time"])
    recovery_time = max(0, int(total_duration) - h2_time)
    instrument_target = (
        f"{DEFAULT_FBG_IP}:{DEFAULT_FBG_PORT}"
        if instrument == "fbg"
        else DEFAULT_POWERMETER_RESOURCE
    )

    return [
        {"phase": "连接设备", "action": "connect_mfc", "target": mfc_port},
        {"phase": "连接设备", "action": "connect_instrument", "instrument": instrument, "target": instrument_target},
        {"phase": "打开MFC2载气", "action": "set_mfc2_flow", "flow_slm": params["mfc2_flow"]},
        {"phase": "等待稳定", "action": "wait_mfc2_stable", "duration_s": DEFAULT_MFC2_STABILIZE_TIME},
        {"phase": "启动数据记录", "action": "start_recording", "duration_s": total_duration, "instrument": instrument},
        {"phase": "执行用户流程", "action": "set_mfc1_flow", "flow_sccm": params["h2_flow"]},
        {"phase": "执行用户流程", "action": "wait_h2", "duration_s": h2_time},
        {"phase": "恢复阶段", "action": "close_mfc1"},
        {"phase": "恢复阶段", "action": "wait_recovery", "duration_s": recovery_time},
        {"phase": "清理设备", "action": "cleanup"},
    ]


def build_run_plan(
    request: str,
    output_folder: str,
    mfc_port: str,
    dry_run: bool = False,
    sensor_name: Optional[str] = None,
    mfc2_flow: Optional[float] = None,
    instrument: Optional[str] = None,
    total_duration: Optional[int] = None,
    loop_interval: int = 60,
    fbg_channel: int = DEFAULT_FBG_CHANNEL,
    high_concentration_authorized: bool = False,
    save_artifacts: bool = False,
) -> Dict:
    params = parse_experiment_request_text(request)

    if sensor_name:
        params["sensor_name"] = sensor_name
    if mfc2_flow is not None:
        params["mfc2_flow"] = float(mfc2_flow)
        params["h2_flow"] = calculate_h2_flow_sccm(
            parse_concentration_percent(params["concentration"]),
            params["mfc2_flow"],
        )
    if instrument:
        params["instrument"] = instrument

    if total_duration is None:
        total_duration = int(params["h2_time"]) + 30

    concentration_percent = parse_concentration_percent(params["concentration"])
    safety_blocked = (
        concentration_percent > HIGH_CONCENTRATION_AUTH_LIMIT_PERCENT
        and not high_concentration_authorized
    )

    plan = {
        "request": request,
        "dry_run": bool(dry_run),
        "output_folder": output_folder,
        "sensor_name": params["sensor_name"],
        "loop_count": params["loop_count"],
        "concentration": params["concentration"],
        "h2_time": params["h2_time"],
        "total_duration": total_duration,
        "loop_interval": loop_interval,
        "instrument": params["instrument"],
        "mfc_port": mfc_port,
        "mfc2_flow": params["mfc2_flow"],
        "h2_flow": params["h2_flow"],
        "fbg_ip": DEFAULT_FBG_IP,
        "fbg_port": DEFAULT_FBG_PORT,
        "fbg_channel": fbg_channel,
        "powermeter_resource": DEFAULT_POWERMETER_RESOURCE,
        "high_concentration_authorized": bool(high_concentration_authorized),
        "save_artifacts": bool(save_artifacts),
        "safety_blocked": safety_blocked,
        "params": params,
    }
    plan["steps"] = _build_steps(params, total_duration, mfc_port)
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a hydrogen sensor experiment from one natural-language request.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Build a plan or run the experiment")
    run_parser.add_argument("request", nargs="+", help="Natural-language experiment request")
    run_parser.add_argument("--output-folder", help="Experiment output folder; omitted runs reuse the last folder")
    run_parser.add_argument("--mfc-port", required=True, help="Confirmed MFC COM port")
    run_parser.add_argument("--sensor-name", help="Override parsed sensor name")
    run_parser.add_argument("--instrument", choices=["powermeter", "fbg"], help="Override instrument")
    run_parser.add_argument("--mfc2-flow", type=float, help="Override MFC2 carrier flow in slm")
    run_parser.add_argument("--total-duration", type=int, help="Recording duration per cycle in seconds")
    run_parser.add_argument("--loop-interval", type=int, default=60, help="Interval between cycles in seconds")
    run_parser.add_argument("--fbg-channel", type=int, default=DEFAULT_FBG_CHANNEL, help="FBG channel")
    run_parser.add_argument("--authorize-high-concentration", action="store_true")
    run_parser.add_argument("--save-artifacts", action="store_true")
    run_parser.add_argument("--dry-run", action="store_true", help="Print the plan without touching hardware")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command != "run":
        parser.print_help()
        return 1

    request = " ".join(args.request)
    try:
        output_folder = resolve_output_folder(args.output_folder)
    except ValueError as e:
        parser.error(str(e))
        return 2

    plan = build_run_plan(
        request=request,
        output_folder=output_folder,
        mfc_port=args.mfc_port,
        dry_run=args.dry_run,
        sensor_name=args.sensor_name,
        mfc2_flow=args.mfc2_flow,
        instrument=args.instrument,
        total_duration=args.total_duration,
        loop_interval=args.loop_interval,
        fbg_channel=args.fbg_channel,
        high_concentration_authorized=args.authorize_high_concentration,
        save_artifacts=args.save_artifacts,
    )

    if args.dry_run:
        _json_print(plan)
        return 0

    if plan["safety_blocked"]:
        _json_print({
            "error": "Hydrogen concentration is above 4.0%; explicit authorization is required before running.",
            "plan": plan,
        })
        return 2

    result = run_hydrogen_experiment(
        request=request,
        output_folder=output_folder,
        mfc_port=args.mfc_port,
        total_duration=plan["total_duration"],
        loop_interval=args.loop_interval,
        powermeter_resource=DEFAULT_POWERMETER_RESOURCE,
        fbg_ip=DEFAULT_FBG_IP,
        fbg_port=DEFAULT_FBG_PORT,
        fbg_channel=args.fbg_channel,
        high_concentration_authorized=args.authorize_high_concentration,
        save_artifacts=args.save_artifacts,
        parsed_params=plan["params"],
    )
    _json_print(result)
    return 0 if result.get("overall_success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
