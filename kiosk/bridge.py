"""Translate controller state into a small view model for the LVGL display."""
import asyncio
import fcntl
import struct
import tomllib
import json
import os
from pathlib import Path
import socket
import sys
import time

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home()/".local/state") / "scanstation"
MODES = ("page", "batch", "multipass", "receipt")
if __package__:
    from .i18n import message
    from .workload import Workload
else:
    from i18n import message
    from workload import Workload


def language():
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home()/".config") / "scanstation/config.toml"
    if not config.exists():
        return "en"
    value = tomllib.loads(config.read_text()).get("ui_language", "en")
    return value if value in ("en", "fr") else "en"


def view(state, now, lang="en"):
    def tr(key, **kw):
        return message(lang, key, **kw)
    phase = state["status"]
    progress = state.get("progress") or {}
    loaded = state.get("loaded")
    waiting = phase == "waiting"
    online = not state.get("sensor_error")
    if not online and phase == "ready":
        scanner = tr("scanner_off")
    elif phase == "ready":
        scanner = tr("ready_full" if loaded else "ready")
    elif waiting:
        scanner = tr("load_next")
    elif phase == "scan":
        scanner = tr("scan")
        if progress.get("stage") == "captured":
            side = progress.get("captured", progress["side"])
            simplex = progress.get("front_only", False)
            scanner = tr("sheet", n=side if simplex else (side+1)//2,
                         side=tr("front" if simplex or side%2 else "back"))
    else:
        scanner = tr("final" if phase == "finalizing" else "busy")

    jobs = state.get("jobs", [])
    deliveries = state.get("deliveries", [])
    lines = []
    for job in jobs:
        item = job.get("progress") or {}
        if job["state"] == "processing":
            stage = item.get("stage") or item.get("event")
            label = tr(stage if stage in ("crop","filter","check_text","orient","clean","name",
                                         "verify_reference","reference","assemble") else "process")
            if item.get("side"):
                label += "  /  " + tr("side_count", n=item["side"], t=item["total_sides"])
            elif item.get("total_documents"):
                label += "  /  " + tr("pdf_count", n=item["document"], t=item["total_documents"])
            lines.append(label)
    queued = sum(j["state"] == "queued" for j in jobs)
    if queued:
        lines.append(tr("queued_batches", n=queued))
    for status in ("failed","uncertain","queued","sending","consuming","verifying"):
        count = sum(d["state"] == status for d in deliveries)
        if count:
            lines.append(f"{tr(status)}  /  {count} PDF")
    if any(j["state"] == "failed" for j in jobs):
        lines.append(tr("proc_error"))
    if (state.get("last") or {}).get("event") == "error":
        lines.append(tr("scan_error"))
    if any(d["state"] == "delivered" and now-d.get("updated",0) < 30 for d in deliveries):
        lines.append(tr("delivered"))
    if not lines:
        if any(j["state"] == "completed" and now-j["updated"] < 20 for j in jobs):
            lines.append(tr("pdf_ready"))
        else:
            lines.append(tr("acquire" if phase == "scan" else "idle"))
    return dict(mode=state["mode"], scanner=scanner, task=lines[int(now//3) % len(lines)],
                select=phase=="ready", scan=online and loaded is True and (phase=="ready" or waiting),
                waiting=waiting, online=online)


async def request(payload):
    reader, writer = await asyncio.open_unix_connection(str(STATE/"control.sock"), limit=8*1024*1024)
    try:
        writer.write(json.dumps(payload).encode()+b"\n")
        await writer.drain()
        return json.loads(await reader.readline())
    finally:
        writer.close()


async def main():
    lang = language()
    meter = Workload()
    bridge, native = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    bridge.setblocking(False)
    proc = await asyncio.create_subprocess_exec("/usr/local/lib/scanstation/kiosk",
                    str(native.fileno()), lang, pass_fds=(native.fileno(),))
    native.close()
    loop = asyncio.get_running_loop()
    command = None
    ack = 0
    previous = None
    notice = ""
    until = 0
    try:
        while True:
            payload = {"action":"status"}
            if command:
                if command in MODES:
                    payload = {"action":"select","mode":command}
                elif command in ("start","next","finish"):
                    payload = {"action":command}
                ack += 1
            try:
                reply = await asyncio.wait_for(request(payload), 8)
                if "error" in reply:
                    notice = message(lang, "empty" if reply["error"] == "Feeder is empty." else "rejected")
                    until = time.time()+6
                    reply = await asyncio.wait_for(request({"action":"status"}), 8)
                model = view(reply, time.time(), lang)
                percent = meter.measure(reply, time.time())
            except (OSError, ValueError, TimeoutError, KeyError):
                percent = -1
                model = dict(mode="", scanner=message(lang,"offline"), task=message(lang,"retry"), online=False,
                             select=False, scan=False, waiting=False)
            if time.time() < until:
                model["task"] = notice
            parts = (ack, model["mode"], int(model["select"]), int(model["scan"]),
                     int(model["waiting"]), model["scanner"], model["task"], percent, int(model["online"]))
            packet = "\t".join(str(v).replace("\t"," ").replace("\n"," ") for v in parts).encode()
            if packet != previous:
                await loop.sock_sendall(bridge, packet)
                previous = packet
            command = None
            try:
                data = await asyncio.wait_for(loop.sock_recv(bridge,128), .35)
                if not data:
                    break
                command = data.decode()
            except TimeoutError:
                pass
    finally:
        bridge.close()
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        await proc.wait()


if __name__ == "__main__":
    # Own the virtual terminal in graphics mode for the entire UI lifetime.
    # setterm alone can be undone when systemd resets the TTY between processes.
    prior = bytearray(4)
    fcntl.ioctl(0, 0x4B3B, prior)  # KDGETMODE
    fcntl.ioctl(0, 0x4B3A, 1)      # KDSETMODE / KD_GRAPHICS
    try:
        asyncio.run(main())
    finally:
        fcntl.ioctl(0, 0x4B3A, struct.unpack("i", prior)[0])
