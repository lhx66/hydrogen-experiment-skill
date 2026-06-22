#!/usr/bin/env python3
"""Run parameterized hydrogen sensor experiment sequences."""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "hydrogen_experiment"
STATE_FILE = Path.home() / ".hydrogen_experiment_skill_state.json"
DEFAULT_MFC2_STABILIZE_TIME = 5
DEFAULT_RECOVERY_TIME = 30

if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from hydrogen_experiment import (  # noqa: E402
    DEFAULT_FBG_CHANNEL,
    DEFAULT_FBG_IP,
    DEFAULT_FBG_PORT,
    DEFAULT_MFC2_FLOW_SLM,
    DEFAULT_POWERMETER_RESOURCE,
    STOP_REQUEST_FILENAME,
    HIGH_CONCENTRATION_AUTH_LIMIT_PERCENT,
    calculate_flow_sequence_duration,
    max_flow_sequence_concentration,
    normalize_flow_steps,
    run_parameterized_hydrogen_experiment,
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

    raise ValueError("First run must specify --output-folder; later runs can reuse the last folder.")


def write_stop_request(output_folder: str, reason: str) -> Path:
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    stop_file = output_path / STOP_REQUEST_FILENAME
    stop_file.write_text(
        json.dumps({"reason": reason}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return stop_file


def close_hydrogen_once(mfc_port: str) -> Dict:
    from mfc_cli import MFCController

    controller = MFCController()
    if not controller.connect(mfc_port, baudrate=9600):
        return {"ok": False, "error": "MFC connect failed"}
    try:
        ok = controller.set_flow(controller.addresses[0], 0)
        return {"ok": bool(ok)}
    finally:
        controller.disconnect()


def _parse_positive_int(value: str, field_name: str) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive number") from None
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return parsed


def parse_step_specs(step_specs: List[str],
                     mfc2_flow: float = DEFAULT_MFC2_FLOW_SLM) -> List[Dict]:
    """Parse CLI step specs into normalized h2/wait steps.

    Supported specs:
    - h2:<percent>:<duration_s>, for example h2:3:20 or h2:3%:20
    - wait:<duration_s>, for example wait:10
    """
    if not step_specs:
        raise ValueError("At least one --step is required")

    raw_steps = []
    for index, spec in enumerate(step_specs, start=1):
        parts = [part.strip() for part in str(spec).split(":")]
        step_type = parts[0].lower() if parts else ""

        if step_type in ("h2", "hydrogen"):
            if len(parts) != 3:
                raise ValueError(f"Step {index} must use h2:<percent>:<duration_s>")
            concentration = parts[1]
            if not concentration.endswith("%"):
                concentration = f"{concentration}%"
            raw_steps.append({
                "type": "h2",
                "concentration": concentration,
                "duration_s": _parse_positive_int(parts[2], "h2 duration"),
            })
        elif step_type in ("wait", "delay", "pause"):
            if len(parts) != 2:
                raise ValueError(f"Step {index} must use wait:<duration_s>")
            raw_steps.append({
                "type": "wait",
                "duration_s": _parse_positive_int(parts[1], "wait duration"),
            })
        else:
            raise ValueError(
                f"Step {index} has unsupported type '{step_type}'. "
                "Use h2:<percent>:<duration_s> or wait:<duration_s>."
            )

    return normalize_flow_steps(raw_steps, mfc2_flow=mfc2_flow)


def _instrument_target(instrument: str) -> str:
    if instrument == "fbg":
        return f"{DEFAULT_FBG_IP}:{DEFAULT_FBG_PORT}"
    return DEFAULT_POWERMETER_RESOURCE


def _build_steps(flow_steps: List[Dict],
                 total_duration: int,
                 mfc_port: str,
                 instrument: str,
                 mfc2_flow: float) -> List[Dict]:
    sequence_duration = calculate_flow_sequence_duration(flow_steps)
    recovery_time = max(0, int(total_duration) - sequence_duration)
    steps = [
        {"phase": "connect_devices", "action": "connect_mfc", "target": mfc_port},
        {
            "phase": "connect_devices",
            "action": "connect_instrument",
            "instrument": instrument,
            "target": _instrument_target(instrument),
        },
        {"phase": "open_carrier", "action": "set_mfc2_flow", "flow_slm": mfc2_flow},
        {"phase": "stabilize_carrier", "action": "wait_mfc2_stable", "duration_s": DEFAULT_MFC2_STABILIZE_TIME},
        {"phase": "record_data", "action": "start_recording", "duration_s": total_duration, "instrument": instrument},
    ]

    for flow_step in flow_steps:
        if flow_step["type"] == "h2":
            steps.extend([
                {
                    "phase": "run_user_flow",
                    "action": "set_mfc1_flow",
                    "concentration": flow_step["concentration"],
                    "flow_sccm": flow_step["h2_flow"],
                },
                {
                    "phase": "run_user_flow",
                    "action": "wait_h2",
                    "duration_s": flow_step["duration_s"],
                },
                {"phase": "run_user_flow", "action": "close_mfc1"},
            ])
        else:
            steps.extend([
                {"phase": "run_user_flow", "action": "close_mfc1"},
                {"phase": "run_user_flow", "action": "wait", "duration_s": flow_step["duration_s"]},
            ])

    if recovery_time:
        steps.extend([
            {"phase": "recovery", "action": "close_mfc1"},
            {"phase": "recovery", "action": "wait_recovery", "duration_s": recovery_time},
        ])
    steps.append({"phase": "cleanup", "action": "cleanup"})
    return steps


def build_run_plan(
    output_folder: str,
    mfc_port: str,
    sensor_name: str,
    instrument: str,
    loop_count: int,
    flow_steps: List[Dict],
    dry_run: bool = False,
    mfc2_flow: float = DEFAULT_MFC2_FLOW_SLM,
    total_duration: Optional[int] = None,
    loop_interval: int = 60,
    fbg_channel: int = DEFAULT_FBG_CHANNEL,
    high_concentration_authorized: bool = False,
    save_artifacts: bool = False,
) -> Dict:
    flow_steps = normalize_flow_steps(flow_steps, mfc2_flow=mfc2_flow)
    sequence_duration = calculate_flow_sequence_duration(flow_steps)
    if total_duration is None:
        total_duration = sequence_duration + DEFAULT_RECOVERY_TIME
    if int(total_duration) < sequence_duration:
        raise ValueError("total_duration must be greater than or equal to the flow sequence duration")

    max_concentration = max_flow_sequence_concentration(flow_steps)
    safety_blocked = (
        max_concentration > HIGH_CONCENTRATION_AUTH_LIMIT_PERCENT
        and not high_concentration_authorized
    )

    plan = {
        "dry_run": bool(dry_run),
        "output_folder": output_folder,
        "sensor_name": sensor_name,
        "loop_count": int(loop_count),
        "flow_steps": flow_steps,
        "sequence_duration": sequence_duration,
        "total_duration": int(total_duration),
        "loop_interval": int(loop_interval),
        "instrument": instrument,
        "mfc_port": mfc_port,
        "mfc2_flow": float(mfc2_flow),
        "max_concentration": max_concentration,
        "fbg_ip": DEFAULT_FBG_IP,
        "fbg_port": DEFAULT_FBG_PORT,
        "fbg_channel": int(fbg_channel),
        "powermeter_resource": DEFAULT_POWERMETER_RESOURCE,
        "high_concentration_authorized": bool(high_concentration_authorized),
        "save_artifacts": bool(save_artifacts),
        "safety_blocked": safety_blocked,
    }
    plan["steps"] = _build_steps(flow_steps, int(total_duration), mfc_port, instrument, float(mfc2_flow))
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run parameterized hydrogen sensor experiment sequences.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Build a plan or run the experiment")
    run_parser.add_argument("--output-folder", help="Experiment output folder; omitted runs reuse the last folder")
    run_parser.add_argument("--mfc-port", required=True, help="Confirmed MFC COM port")
    run_parser.add_argument("--sensor-name", required=True, help="Sensor or sample name")
    run_parser.add_argument("--instrument", choices=["powermeter", "fbg"], required=True, help="Acquisition instrument")
    run_parser.add_argument("--loop-count", type=int, default=1, help="Number of cycles to run")
    run_parser.add_argument(
        "--step",
        action="append",
        required=True,
        help="Flow step. Use h2:<percent>:<duration_s> or wait:<duration_s>. Repeat for sequences.",
    )
    run_parser.add_argument("--mfc2-flow", type=float, default=DEFAULT_MFC2_FLOW_SLM, help="MFC2 carrier flow in slm")
    run_parser.add_argument("--total-duration", type=int, help="Recording duration per cycle in seconds")
    run_parser.add_argument("--loop-interval", type=int, default=60, help="Interval between cycles in seconds")
    run_parser.add_argument("--fbg-channel", type=int, default=DEFAULT_FBG_CHANNEL, help="FBG channel")
    run_parser.add_argument("--authorize-high-concentration", action="store_true")
    run_parser.add_argument("--save-artifacts", action="store_true")
    run_parser.add_argument("--dry-run", action="store_true", help="Print the plan without touching hardware")
    stop_parser = subparsers.add_parser("stop", help="Request a running experiment to stop")
    stop_parser.add_argument("--output-folder", help="Experiment output folder; omitted runs reuse the last folder")
    stop_parser.add_argument("--reason", default="User requested stop", help="Stop reason")
    stop_parser.add_argument("--mfc-port", help="Optional COM port to close MFC1 immediately")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "stop":
        try:
            output_folder = resolve_output_folder(args.output_folder)
            stop_file = write_stop_request(output_folder, args.reason)
            payload = {
                "status": "stop_requested",
                "stop_file": str(stop_file),
                "reason": args.reason,
            }
            if args.mfc_port:
                payload["close_hydrogen"] = close_hydrogen_once(args.mfc_port)
            _json_print(payload)
            return 0
        except ValueError as e:
            parser.error(str(e))
            return 2

    if args.command != "run":
        parser.print_help()
        return 1

    try:
        output_folder = resolve_output_folder(args.output_folder)
        flow_steps = parse_step_specs(args.step, mfc2_flow=args.mfc2_flow)
        plan = build_run_plan(
            output_folder=output_folder,
            mfc_port=args.mfc_port,
            sensor_name=args.sensor_name,
            instrument=args.instrument,
            loop_count=args.loop_count,
            flow_steps=flow_steps,
            dry_run=args.dry_run,
            mfc2_flow=args.mfc2_flow,
            total_duration=args.total_duration,
            loop_interval=args.loop_interval,
            fbg_channel=args.fbg_channel,
            high_concentration_authorized=args.authorize_high_concentration,
            save_artifacts=args.save_artifacts,
        )
    except ValueError as e:
        parser.error(str(e))
        return 2

    if args.dry_run:
        _json_print(plan)
        return 0

    if plan["safety_blocked"]:
        _json_print({
            "error": "Hydrogen concentration is above 4.0%; explicit authorization is required before running.",
            "plan": plan,
        })
        return 2

    result = run_parameterized_hydrogen_experiment(
        output_folder=output_folder,
        mfc_port=args.mfc_port,
        sensor_name=args.sensor_name,
        instrument=args.instrument,
        loop_count=args.loop_count,
        flow_steps=plan["flow_steps"],
        mfc2_flow=args.mfc2_flow,
        total_duration=plan["total_duration"],
        loop_interval=args.loop_interval,
        powermeter_resource=DEFAULT_POWERMETER_RESOURCE,
        fbg_ip=DEFAULT_FBG_IP,
        fbg_port=DEFAULT_FBG_PORT,
        fbg_channel=args.fbg_channel,
        high_concentration_authorized=args.authorize_high_concentration,
        save_artifacts=args.save_artifacts,
    )
    _json_print(result)
    return 0 if result.get("overall_success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
