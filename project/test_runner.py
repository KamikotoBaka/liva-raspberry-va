from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import platform
import shutil
import statistics
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    import psutil
except ImportError:  # pragma: no cover - optional dependency guard
    psutil = None


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = PROJECT_ROOT / "tests" / "voice_commands.json"
EXAMPLE_MANIFEST = PROJECT_ROOT / "tests" / "voice_commands.example.json"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "benchmark_results"


@dataclass
class ResourceSample:
    timestamp: float
    cpu_percent: float | None = None
    ram_percent: float | None = None
    ram_used_mb: float | None = None
    ram_total_mb: float | None = None
    gpu_percent: float | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None


class ResourceSampler:
    def __init__(self, interval_seconds: float = 0.25) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[ResourceSample] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if psutil is not None:
            psutil.cpu_percent(interval=None)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.samples.append(self._sample_once())
            self._stop_event.wait(self.interval_seconds)

    def _sample_once(self) -> ResourceSample:
        timestamp = time.perf_counter()
        sample = ResourceSample(timestamp=timestamp)

        if psutil is not None:
            try:
                memory = psutil.virtual_memory()
                sample.cpu_percent = float(psutil.cpu_percent(interval=None))
                sample.ram_percent = float(memory.percent)
                sample.ram_used_mb = float(memory.used / (1024 * 1024))
                sample.ram_total_mb = float(memory.total / (1024 * 1024))
            except Exception:
                pass

        gpu_sample = self._sample_gpu()
        if gpu_sample is not None:
            sample.gpu_percent = gpu_sample.get("gpu_percent")
            sample.gpu_memory_used_mb = gpu_sample.get("gpu_memory_used_mb")
            sample.gpu_memory_total_mb = gpu_sample.get("gpu_memory_total_mb")

        return sample

    def _sample_gpu(self) -> dict[str, float] | None:
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            return self._sample_with_nvidia_smi(nvidia_smi)

        tegrastats = shutil.which("tegrastats")
        if tegrastats:
            return self._sample_with_tegrastats(tegrastats)

        return None

    def _sample_with_nvidia_smi(self, executable: str) -> dict[str, float] | None:
        command = [
            executable,
            "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=5)
        except Exception:
            return None

        if completed.returncode != 0:
            return None

        gpu_percents: list[float] = []
        gpu_memory_used: list[float] = []
        gpu_memory_total: list[float] = []

        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue

            try:
                gpu_percents.append(float(parts[0]))
                gpu_memory_used.append(float(parts[1]))
                gpu_memory_total.append(float(parts[2]))
            except ValueError:
                continue

        if not gpu_percents:
            return None

        return {
            "gpu_percent": max(gpu_percents),
            "gpu_memory_used_mb": max(gpu_memory_used),
            "gpu_memory_total_mb": max(gpu_memory_total),
        }

    def _sample_with_tegrastats(self, executable: str) -> dict[str, float] | None:
        command = [executable, "--interval", "250"]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            return None

        try:
            if process.stdout is None:
                return None
            line = process.stdout.readline().strip()
        except Exception:
            line = ""
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except Exception:
                process.kill()

        if not line:
            return None

        gpu_percent = self._extract_number(line, r"GR3D_FREQ\s+(\d+)%")
        result: dict[str, float] = {}
        if gpu_percent is not None:
            result["gpu_percent"] = gpu_percent
        return result or None

    @staticmethod
    def _extract_number(text: str, pattern: str) -> float | None:
        import re

        match = re.search(pattern, text)
        if match is None:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None


def load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        if EXAMPLE_MANIFEST.exists():
            raise FileNotFoundError(
                f"Manifest not found: {manifest_path}. Copy {EXAMPLE_MANIFEST} to {manifest_path} and fill in your commands."
            )
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError("Manifest must contain a JSON array of command entries")

    entries: list[dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Manifest entry {index} must be an object")
        entries.append(item)
    return entries


def resolve_path(value: str | None, base_dir: Path) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()

    search_roots = [base_dir, PROJECT_ROOT]
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved

    return (base_dir / candidate).resolve()


def entry_input(entry: dict[str, Any], base_dir: Path, mode: str) -> tuple[str, Path | None, str]:
    if mode == "audio":
        audio_value = entry.get("audio") or entry.get("audioPath") or entry.get("file")
        audio_path = resolve_path(str(audio_value) if audio_value is not None else None, base_dir)
        if audio_path is None:
            raise ValueError("Audio mode requires an 'audio' field")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        label = str(entry.get("transcript") or entry.get("text") or audio_path.name)
        return label, audio_path, audio_path.name

    text_value = entry.get("text") or entry.get("transcript")
    if not isinstance(text_value, str) or not text_value.strip():
        raise ValueError("Text mode requires a non-empty 'text' or 'transcript' field")
    return text_value.strip(), None, text_value.strip()


def request_endpoint(mode: str) -> str:
    if mode == "audio":
        return "/api/process-audio"
    return "/api/chat/turn"


def post_payload(client: httpx.Client, base_url: str, mode: str, text_or_audio: str, audio_path: Path | None, timeout: float, include_server_timings: bool = False) -> tuple[int, dict[str, Any], str]:
    url = f"{base_url.rstrip('/')}{request_endpoint(mode)}"
    if include_server_timings:
        sep = "?" if "?" not in url else "&"
        url = f"{url}{sep}debug=1"
    if mode == "audio":
        assert audio_path is not None
        mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        with audio_path.open("rb") as handle:
            response = client.post(
                url,
                files={"audio": (audio_path.name, handle, mime_type)},
                timeout=timeout,
            )
    else:
        response = client.post(url, json={"text": text_or_audio}, timeout=timeout)

    response_text = response.text
    try:
        response_json = response.json()
        if not isinstance(response_json, dict):
            response_json = {"value": response_json}
    except Exception:
        response_json = {}

    return response.status_code, response_json, response_text


def value_preview(value: Any, limit: int = 180) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def summarize_samples(samples: list[ResourceSample]) -> dict[str, float | None]:
    cpu_values = [sample.cpu_percent for sample in samples if sample.cpu_percent is not None]
    ram_values = [sample.ram_percent for sample in samples if sample.ram_percent is not None]
    ram_used_values = [sample.ram_used_mb for sample in samples if sample.ram_used_mb is not None]
    gpu_values = [sample.gpu_percent for sample in samples if sample.gpu_percent is not None]
    gpu_memory_used_values = [sample.gpu_memory_used_mb for sample in samples if sample.gpu_memory_used_mb is not None]

    return {
        "cpu_avg_pct": statistics.mean(cpu_values) if cpu_values else None,
        "cpu_peak_pct": max(cpu_values) if cpu_values else None,
        "ram_avg_pct": statistics.mean(ram_values) if ram_values else None,
        "ram_peak_pct": max(ram_values) if ram_values else None,
        "ram_peak_used_mb": max(ram_used_values) if ram_used_values else None,
        "gpu_avg_pct": statistics.mean(gpu_values) if gpu_values else None,
        "gpu_peak_pct": max(gpu_values) if gpu_values else None,
        "gpu_peak_used_mb": max(gpu_memory_used_values) if gpu_memory_used_values else None,
    }


def run_benchmark(args: argparse.Namespace) -> list[dict[str, Any]]:
    manifest_path = resolve_path(args.manifest, PROJECT_ROOT) or DEFAULT_MANIFEST
    entries = load_manifest(manifest_path)
    base_dir = manifest_path.parent
    endpoint = request_endpoint(args.mode)

    rows: list[dict[str, Any]] = []

    with httpx.Client() as client:
        for entry in entries:
            command_id = str(entry.get("id") or entry.get("name") or entry.get("trigger") or "command")
            expected_intent = str(entry.get("expected_intent") or entry.get("intent") or "")
            label, resolved_path, input_value = entry_input(entry, base_dir, args.mode)

            if args.warmup_runs > 0:
                for _ in range(args.warmup_runs):
                    try:
                        post_payload(client, args.base_url, args.mode, label, resolved_path, args.timeout, args.include_server_timings)
                    except Exception:
                        pass

            for run_index in range(1, args.repeats + 1):
                sampler = ResourceSampler(interval_seconds=args.sample_interval_seconds)
                sampler.start()
                start = time.perf_counter()
                status_code: int | None = None
                response_json: dict[str, Any] = {}
                response_text = ""
                error_text = ""

                try:
                    status_code, response_json, response_text = post_payload(
                        client,
                        args.base_url,
                        args.mode,
                        label,
                        resolved_path,
                        args.timeout,
                        args.include_server_timings,
                    )
                except Exception as exc:
                    error_text = f"{type(exc).__name__}: {exc}"
                finally:
                    latency_ms = (time.perf_counter() - start) * 1000.0
                    sampler.stop()

                resource_summary = summarize_samples(sampler.samples)
                response_intent = response_json.get("intent")
                response_route = response_json.get("route")
                response_tts = response_json.get("ttsText") or response_json.get("message") or response_json.get("detail")
                if not error_text and status_code is not None and status_code >= 400:
                    error_text = value_preview(response_text)

                # extract server-side debug timings if present
                debug = response_json.get("debugTimings") if isinstance(response_json, dict) else {}
                deltas = debug.get("deltas_ms") if isinstance(debug, dict) else {}
                def _num(v):
                    try:
                        return round(float(v), 2)
                    except Exception:
                        return ""
                server_dispatch_ms = _num(deltas.get("dispatch_ms") if deltas else None)
                server_tts_ms = _num(deltas.get("tts_ms") if deltas else None)
                server_total_ms = _num(deltas.get("total_ms") if deltas else None)
                server_dispatch_offset_ms = _num(deltas.get("dispatch_offset_ms") if deltas else None)

                rows.append(
                    {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "hardware": args.hardware,
                        "host": platform.node(),
                        "os": platform.platform(),
                        "python": platform.python_version(),
                        "mode": args.mode,
                        "endpoint": endpoint,
                        "base_url": args.base_url,
                        "whisper_model": args.whisper_model,
                        "llm_model": args.llm_model,
                        "command_id": command_id,
                        "run_index": run_index,
                        "input_value": input_value,
                        "audio_file": resolved_path.name if resolved_path is not None else "",
                        "expected_intent": expected_intent,
                        "status_code": status_code,
                        "latency_ms": round(latency_ms, 2),
                        "cpu_avg_pct": round(resource_summary["cpu_avg_pct"], 2) if resource_summary["cpu_avg_pct"] is not None else "",
                        "cpu_peak_pct": round(resource_summary["cpu_peak_pct"], 2) if resource_summary["cpu_peak_pct"] is not None else "",
                        "ram_avg_pct": round(resource_summary["ram_avg_pct"], 2) if resource_summary["ram_avg_pct"] is not None else "",
                        "ram_peak_pct": round(resource_summary["ram_peak_pct"], 2) if resource_summary["ram_peak_pct"] is not None else "",
                        "ram_peak_used_mb": round(resource_summary["ram_peak_used_mb"], 2) if resource_summary["ram_peak_used_mb"] is not None else "",
                        "gpu_avg_pct": round(resource_summary["gpu_avg_pct"], 2) if resource_summary["gpu_avg_pct"] is not None else "",
                        "gpu_peak_pct": round(resource_summary["gpu_peak_pct"], 2) if resource_summary["gpu_peak_pct"] is not None else "",
                        "gpu_peak_used_mb": round(resource_summary["gpu_peak_used_mb"], 2) if resource_summary["gpu_peak_used_mb"] is not None else "",
                        "response_intent": value_preview(response_intent),
                        "response_route": value_preview(response_route),
                        "response_command_text": value_preview(response_json.get("commandText")),
                        "response_tts_text": value_preview(response_tts),
                        "server_dispatch_ms": server_dispatch_ms,
                        "server_tts_ms": server_tts_ms,
                        "server_total_ms": server_total_ms,
                        "server_dispatch_offset_ms": server_dispatch_offset_ms,
                        "error": error_text,
                    }
                )

    return rows


def aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("hardware", "")),
            str(row.get("mode", "")),
            str(row.get("whisper_model", "")),
            str(row.get("llm_model", "")),
            str(row.get("command_id", "")),
        )
        grouped[key].append(row)

    summary_rows: list[dict[str, Any]] = []
    for (hardware, mode, whisper_model, llm_model, command_id), items in sorted(grouped.items()):
        latencies = [float(item["latency_ms"]) for item in items if item.get("latency_ms") not in {"", None}]
        cpu_avg_values = [float(item["cpu_avg_pct"]) for item in items if item.get("cpu_avg_pct") not in {"", None}]
        cpu_peak_values = [float(item["cpu_peak_pct"]) for item in items if item.get("cpu_peak_pct") not in {"", None}]
        ram_avg_values = [float(item["ram_avg_pct"]) for item in items if item.get("ram_avg_pct") not in {"", None}]
        ram_peak_values = [float(item["ram_peak_pct"]) for item in items if item.get("ram_peak_pct") not in {"", None}]
        ram_used_values = [float(item["ram_peak_used_mb"]) for item in items if item.get("ram_peak_used_mb") not in {"", None}]
        gpu_avg_values = [float(item["gpu_avg_pct"]) for item in items if item.get("gpu_avg_pct") not in {"", None}]
        gpu_peak_values = [float(item["gpu_peak_pct"]) for item in items if item.get("gpu_peak_pct") not in {"", None}]
        gpu_used_values = [float(item["gpu_peak_used_mb"]) for item in items if item.get("gpu_peak_used_mb") not in {"", None}]

        summary_rows.append(
            {
                "hardware": hardware,
                "mode": mode,
                "whisper_model": whisper_model,
                "llm_model": llm_model,
                "command_id": command_id,
                "runs": len(items),
                "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else "",
                "p95_latency_ms": round(_percentile(latencies, 95), 2) if latencies else "",
                "min_latency_ms": round(min(latencies), 2) if latencies else "",
                "max_latency_ms": round(max(latencies), 2) if latencies else "",
                "avg_cpu_pct": round(statistics.mean(cpu_avg_values), 2) if cpu_avg_values else "",
                "peak_cpu_pct": round(max(cpu_peak_values), 2) if cpu_peak_values else "",
                "avg_ram_pct": round(statistics.mean(ram_avg_values), 2) if ram_avg_values else "",
                "peak_ram_pct": round(max(ram_peak_values), 2) if ram_peak_values else "",
                "peak_ram_used_mb": round(max(ram_used_values), 2) if ram_used_values else "",
                "avg_gpu_pct": round(statistics.mean(gpu_avg_values), 2) if gpu_avg_values else "",
                "peak_gpu_pct": round(max(gpu_peak_values), 2) if gpu_peak_values else "",
                "peak_gpu_used_mb": round(max(gpu_used_values), 2) if gpu_used_values else "",
                "error_count": sum(1 for item in items if str(item.get("error", "")).strip()),
            }
        )

    return summary_rows


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if len(values) == 1:
        return values[0]

    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * (percentile / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark LIVA latency and system usage")
    parser.add_argument("--base-url", default=os.getenv("LIVA_BENCHMARK_URL", "http://0.0.0.0:8000"))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--mode", choices=("audio", "text"), default="audio")
    parser.add_argument("--hardware", default=os.getenv("LIVA_HARDWARE_LABEL", platform.node() or "unknown"))
    parser.add_argument("--whisper-model", default=os.getenv("WHISPER_MODEL", os.getenv("LIVA_WHISPER_MODEL", "unknown")))
    parser.add_argument("--llm-model", default=os.getenv("LLM_MODEL", os.getenv("LIVA_THINKING_MODEL", "unknown")))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--sample-interval-seconds", type=float, default=0.25)
    parser.add_argument("--output-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument(
        "--include-server-timings",
        action="store_true",
        dest="include_server_timings",
        help="Request server to include per-stage debug timings in responses",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    if args.warmup_runs < 0:
        raise SystemExit("--warmup-runs cannot be negative")

    rows = run_benchmark(args)
    summaries = aggregate_rows(rows)

    output_dir = Path(args.output_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = output_dir / f"benchmark_raw_{args.hardware}_{timestamp}.csv"
    summary_path = output_dir / f"benchmark_summary_{args.hardware}_{timestamp}.csv"

    raw_fields = [
        "timestamp_utc",
        "hardware",
        "host",
        "os",
        "python",
        "mode",
        "endpoint",
        "base_url",
        "whisper_model",
        "llm_model",
        "command_id",
        "run_index",
        "input_value",
        "audio_file",
        "expected_intent",
        "status_code",
        "latency_ms",
        "cpu_avg_pct",
        "cpu_peak_pct",
        "ram_avg_pct",
        "ram_peak_pct",
        "ram_peak_used_mb",
        "gpu_avg_pct",
        "gpu_peak_pct",
        "gpu_peak_used_mb",
        "response_intent",
        "response_route",
        "response_command_text",
        "response_tts_text",
        "server_dispatch_ms",
        "server_tts_ms",
        "server_total_ms",
        "server_dispatch_offset_ms",
        "error",
    ]

    summary_fields = [
        "hardware",
        "mode",
        "whisper_model",
        "llm_model",
        "command_id",
        "runs",
        "avg_latency_ms",
        "p95_latency_ms",
        "min_latency_ms",
        "max_latency_ms",
        "avg_cpu_pct",
        "peak_cpu_pct",
        "avg_ram_pct",
        "peak_ram_pct",
        "peak_ram_used_mb",
        "avg_gpu_pct",
        "peak_gpu_pct",
        "peak_gpu_used_mb",
        "error_count",
    ]

    write_csv(raw_path, rows, raw_fields)
    write_csv(summary_path, summaries, summary_fields)

    print(f"Raw results: {raw_path}")
    print(f"Summary results: {summary_path}")
    print(f"Commands tested: {len(rows)}")
    print(f"Manifest: {resolve_path(args.manifest, PROJECT_ROOT) or DEFAULT_MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())