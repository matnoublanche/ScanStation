"""Translate controller state into a small view model for the LVGL display."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import time

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home()/".local/state") / "scanstation"
MODES = ("page", "batch", "multipass", "receipt")
STAGES = {"crop":"Cropping", "filter":"Checking blank sides", "check_text":"Checking text",
          "orient":"Rotating", "clean":"Cleaning", "name":"Reading title",
          "verify_reference":"Checking reference", "assemble":"Creating PDF"}
DELIVERY = {"queued":"Queued for Paperless", "sending":"Sending to Paperless",
            "consuming":"Paperless processing", "verifying":"Checking Inbox",
            "failed":"Paperless delivery failed", "uncertain":"Check Paperless delivery"}


def view(state, now):
    phase = state["status"]
    progress = state.get("progress") or {}
    loaded = state.get("loaded")
    waiting = phase == "waiting"
    online = not state.get("sensor_error")
    if not online and phase == "ready":
        scanner = "Scanner offline"
    elif phase == "ready":
        scanner = "Ready  /  paper loaded" if loaded else "Ready  /  load paper"
    elif waiting:
        scanner = "Load next pass"
    elif phase == "scan":
        scanner = "Scanning"
        if progress.get("stage") == "captured":
            side = progress["side"]
            scanner = f"Scanning  /  sheet {(side+1)//2}, {'front' if side%2 else 'back'}"
    else:
        scanner = "Finalizing" if phase == "finalizing" else "Scanner busy"

    jobs = state.get("jobs", [])
    deliveries = state.get("deliveries", [])
    lines = []
    for job in jobs:
        item = job.get("progress") or {}
        if job["state"] == "processing":
            stage = item.get("stage") or item.get("event")
            label = STAGES.get(stage, "Processing")
            if item.get("side"):
                label += f"  /  side {item['side']} of {item['total_sides']}"
            elif item.get("total_documents"):
                label += f"  /  PDF {item['document']} of {item['total_documents']}"
            lines.append(label)
    queued = sum(j["state"] == "queued" for j in jobs)
    if queued:
        lines.append(f"{queued} batch{'es' if queued != 1 else ''} queued")
    for status, label in DELIVERY.items():
        count = sum(d["state"] == status for d in deliveries)
        if count:
            lines.append(f"{label}  /  {count} PDF" + ("s" if count != 1 else ""))
    if any(j["state"] == "failed" for j in jobs):
        lines.append("Processing failed  /  check job")
    if (state.get("last") or {}).get("event") == "error":
        lines.append("Scan failed  /  check feeder")
    recent = [d for d in deliveries if d["state"] == "delivered" and now-d.get("updated",0) < 30]
    if recent:
        lines.append("Paperless received  /  Inbox verified")
    if not lines:
        if any(j["state"] == "completed" and now-j["updated"] < 20 for j in jobs):
            lines.append("PDF ready")
        else:
            lines.append("Acquiring originals" if phase == "scan" else "No pending tasks")
    return dict(mode=state["mode"], scanner=scanner, task=lines[int(now//3) % len(lines)],
                select=phase=="ready", scan=online and loaded is True and (phase=="ready" or waiting),
                waiting=waiting)


async def request(payload):
    reader, writer = await asyncio.open_unix_connection(str(STATE/"control.sock"), limit=8*1024*1024)
    try:
        writer.write(json.dumps(payload).encode()+b"\n")
        await writer.drain()
        return json.loads(await reader.readline())
    finally:
        writer.close()


async def main():
    bridge, native = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    bridge.setblocking(False)
    proc = await asyncio.create_subprocess_exec("/usr/local/lib/scanstation/kiosk",
                    str(native.fileno()), pass_fds=(native.fileno(),))
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
                    notice, until = reply["error"], time.time()+6
                    reply = await asyncio.wait_for(request({"action":"status"}), 8)
                model = view(reply, time.time())
            except (OSError, ValueError, TimeoutError, KeyError):
                model = dict(mode="", scanner="Controller offline", task="Reconnecting",
                             select=False, scan=False, waiting=False)
            if time.time() < until:
                model["task"] = notice
            parts = (ack, model["mode"], int(model["select"]), int(model["scan"]),
                     int(model["waiting"]), model["scanner"], model["task"])
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
    asyncio.run(main())
