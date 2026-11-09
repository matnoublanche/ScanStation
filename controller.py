"""Local ScanStation controller for hardware sensors and client requests."""
import argparse
import asyncio
import contextlib
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib

from jobqueue import Queue

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home()/".local/state") / "scanstation"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home()/".config") / "scanstation/config.toml"
MODES = ("batch", "page", "sheet", "multipass", "receipt")
COMMANDS = ("select", "start", "status", "next", "finish")
ENGINE = "/usr/local/bin/scanstation"


def running_job():
    with (STATE/"scanner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


class Sensors:
    """Keep one idle SANE handle and release it before capture."""
    def __init__(self):
        import sane
        self.sane = sane
        sane.init()
        self.dev = self.guard = None
        self.device_name = None

    def close(self):
        try:
            if self.dev is not None:
                self.dev.close()
        finally:
            self.dev = None
            if self.guard:
                self.guard.close()
                self.guard = None

    def read(self):
        if self.dev is None:
            self.guard = (STATE/"device.lock").open("a")
            fcntl.flock(self.guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            settings = tomllib.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
            device = settings.get("device", os.getenv("SCANSTATION_DEVICE", "auto"))
            if device == "auto":
                names = [d[0] for d in self.sane.get_devices(True) if d[0].startswith("epjitsu:")]
                if len(names) != 1:
                    raise ValueError("Connect the scanner or specify device in config.toml.")
                device = names[0]
            self.dev = self.sane.open(device)
            self.device_name = device
        # The SANE scan option shares its name with the Python scan() method.
        pressed = self.dev.dev.get_option(self.dev.opt["scan"].index)
        return bool(pressed), bool(self.dev.page_loaded)


def remember(mode):
    with tempfile.NamedTemporaryFile("w", dir=STATE, delete=False) as tmp:
        tmp.write(mode + "\n")
    os.replace(tmp.name, STATE/"selection")


class Controller:
    def __init__(self, sensors):
        self.queue = Queue()
        self.sensors = sensors
        saved = STATE/"selection"
        self.mode = saved.read_text().strip() if saved.exists() else "batch"
        self.mode = {"lot": "batch", "feuille": "sheet", "multipassage": "multipass",
                     "ticket": "receipt"}.get(self.mode, self.mode)
        if self.mode not in MODES:
            raise ValueError("Invalid saved selection.")
        self.phase = "ready"
        self.loaded = None
        self.hardware_error = None
        self.armed = False
        self.proc = None
        self.last = None
        self.progress = None
        self.mutex = asyncio.Lock()

    def status(self):
        phase = "busy" if self.phase == "ready" and running_job() else self.phase
        jobs = self.queue.snapshot()
        finished = [j for j in jobs if j["state"] in ("completed","failed")]
        last = max(finished, key=lambda j:j["updated"])["progress"] if finished else None
        if self.last and self.last.get("event") == "error":
            last = self.last
        return dict(mode=self.mode, status=phase, loaded=self.loaded, jobs=jobs, delivery_counts=self.queue.delivery_counts(), deliveries=self.queue.delivery_status(),
                    sensor_error=self.hardware_error, progress=self.progress, last=last)

    async def sample(self):
        try:
            pressed, self.loaded = await asyncio.to_thread(self.sensors.read)
            self.hardware_error = None
            return pressed
        except Exception as exc:
            self.hardware_error = str(exc)
            self.loaded = None
            self.armed = False
            self.sensors.close()
            return None

    async def start(self, origin):
        print(f"Starting from {origin}: {self.mode}", flush=True)
        self.sensors.close()
        self.loaded = None
        self.armed = False
        mode = "page" if self.mode == "receipt" else self.mode
        profile = "receipt" if self.mode == "receipt" else "document"
        self.proc = await asyncio.create_subprocess_exec(
            ENGINE, mode, "--device", self.sensors.device_name, "--profile", profile, "--json", "--enqueue", stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE)
        self.phase = "scan"
        self.progress = None
        asyncio.create_task(self.follow(self.proc))

    async def follow(self, proc):
        result = None
        try:
            async for line in proc.stdout:
                item = json.loads(line)
                async with self.mutex:
                    self.progress = item
                    if item["event"] == "waiting":
                        self.phase = "waiting"
                        self.armed = False
                    if item["event"] in ("queued", "error"):
                        result = item
        finally:
            rc = await proc.wait()
            async with self.mutex:
                self.last = result or dict(event="error", message=f"Engine stopped (exit {rc}).")
                self.proc = None
                self.phase = "ready"
                self.armed = False

    async def resume(self, command):
        self.sensors.close()
        self.armed = False
        self.loaded = None
        self.proc.stdin.write(b"finish\n" if command == "finish" else b"next\n")
        await self.proc.stdin.drain()
        self.phase = "finalizing" if command == "finish" else "scan"

    async def poll(self):
        while True:
            async with self.mutex:
                if self.phase == "waiting" or (self.phase == "ready" and not running_job()):
                    pressed = await self.sample()
                    if pressed is False:
                        self.armed = True
                    elif pressed and self.armed:
                        self.armed = False
                        if self.loaded:
                            if self.phase == "waiting":
                                await self.resume("next")
                            else:
                                await self.start("button")
                else:
                    self.sensors.close()
                    self.loaded = None
                    self.armed = False
            await asyncio.sleep(2 if self.hardware_error else .20)

    async def request(self, command):
        action = command["action"]
        async with self.mutex:
            if action == "status":
                return self.status()
            if self.phase == "waiting" and action in ("next", "finish"):
                if action == "next":
                    await self.sample()
                    if not self.loaded:
                        raise ValueError(self.hardware_error or "Feeder is empty.")
                await self.resume(action)
            elif self.phase != "ready" or running_job():
                raise ValueError("A job is already running.")
            elif action in ("select", "start"):
                if action == "select":
                    mode = command["mode"]
                    if mode not in MODES:
                        raise ValueError("Unknown mode.")
                    remember(mode)
                    self.mode = mode
                if action == "start" or command.get("if_loaded"):
                    await self.sample()
                    if self.loaded:
                        await self.start("command")
                    elif action == "start" or self.hardware_error:
                        raise ValueError(self.hardware_error or "Feeder is empty.")
            else:
                raise ValueError("Command unavailable in the current state.")
            return self.status()


async def serve():
    STATE.mkdir(parents=True, exist_ok=True)
    controller = Controller(Sensors())
    async def handle(reader, writer):
        try:
            request = json.loads(await asyncio.wait_for(reader.readline(), 5))
            reply = await controller.request(request)
        except Exception as exc:
            reply = {"error": str(exc)}
        try:
            writer.write(json.dumps(reply).encode()+b"\n")
            await writer.drain()
        finally:
            writer.close()

    path = STATE/"control.sock"
    path.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle, path=str(path))
    os.chmod(path, 0o600)
    async with server:
        await controller.poll()


async def client(args):
    reader, writer = await asyncio.open_unix_connection(str(STATE/"control.sock"))
    try:
        writer.write(json.dumps(vars(args)).encode()+b"\n")
        await writer.drain()
        reply = json.loads(await reader.readline())
    finally:
        writer.close()
    if args.json:
        print(json.dumps(reply, ensure_ascii=False))
    else:
        print(reply.get("error") or f"{reply['mode']} · {reply['status']} · feeder loaded: {reply['loaded']}")
        if reply.get("sensor_error"):
            print(reply["sensor_error"])
        if reply.get("last"):
            print(json.dumps(reply["last"], ensure_ascii=False))
    return int("error" in reply)


if __name__ == "__main__":
    if sys.argv[1:] == ["service"]:
        asyncio.run(serve())
    else:
        parser = argparse.ArgumentParser(prog="scanstation")
        parser.add_argument("action", choices=COMMANDS)
        parser.add_argument("mode", nargs="?", choices=MODES)
        parser.add_argument("--start-if-loaded", dest="if_loaded", action="store_true")
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args()
        if (args.action == "select") != bool(args.mode) or (args.if_loaded and args.action != "select"):
            parser.error("Use select MODE [--start-if-loaded] or an action without a mode.")
        try:
            sys.exit(asyncio.run(client(args)))
        except (OSError, ValueError) as exc:
            msg = f"ScanStation service unavailable : {exc}"
            print(json.dumps({"error": msg}) if args.json else msg)
            sys.exit(1)
