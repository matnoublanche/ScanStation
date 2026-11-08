"""Interface locale entre le moteur ScanStation, les capteurs et les commandes."""
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

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home()/".local/state") / "scanstation"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home()/".config") / "scanstation/config.toml"
MODES = ("lot", "feuille", "multipassage", "ticket")
COMMANDS = ("choisir", "demarrer", "etat", "suivant", "terminer")
ENGINE = "/usr/local/bin/scanstation"


def running_job():
    with (STATE/"scanner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


class Sensors:
    """Un seul handle SANE au repos, libéré avant chaque acquisition."""
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
                    raise ValueError("Brancher le scanner ou préciser device dans config.toml.")
                device = names[0]
            self.dev = self.sane.open(device)
            self.device_name = device
        # L'option SANE "scan" porte le même nom que la méthode Python scan().
        pressed = self.dev.dev.get_option(self.dev.opt["scan"].index)
        return bool(pressed), bool(self.dev.page_loaded)


def remember(mode):
    with tempfile.NamedTemporaryFile("w", dir=STATE, delete=False) as tmp:
        tmp.write(mode + "\n")
    os.replace(tmp.name, STATE/"selection")


class Controller:
    def __init__(self, sensors):
        self.sensors = sensors
        saved = STATE/"selection"
        self.mode = saved.read_text().strip() if saved.exists() else "lot"
        if self.mode not in MODES:
            raise ValueError("Sélection enregistrée invalide.")
        self.phase = "pret"
        self.loaded = None
        self.hardware_error = None
        self.armed = False
        self.proc = None
        self.last = None
        self.progress = None
        self.mutex = asyncio.Lock()

    def status(self):
        phase = "occupe" if self.phase == "pret" and running_job() else self.phase
        return dict(mode=self.mode, etat=phase, charge=self.loaded,
                    erreur_capteur=self.hardware_error, progression=self.progress, dernier=self.last)

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
        print(f"Départ {origin} : {self.mode}", flush=True)
        self.sensors.close()
        self.loaded = None
        self.armed = False
        mode = "lot" if self.mode == "ticket" else self.mode
        profile = "ticket" if self.mode == "ticket" else "document"
        self.proc = await asyncio.create_subprocess_exec(
            ENGINE, mode, "--device", self.sensors.device_name, "--profil", profile, "--json", stdin=asyncio.subprocess.PIPE,
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
                    if item["event"] == "attente":
                        self.phase = "attente"
                        self.armed = False
                    if item["event"] in ("termine", "erreur"):
                        result = item
        finally:
            rc = await proc.wait()
            async with self.mutex:
                self.last = result or dict(event="erreur", message=f"Moteur arrêté (code {rc}).")
                self.proc = None
                self.phase = "pret"
                self.armed = False

    async def resume(self, command):
        self.sensors.close()
        self.armed = False
        self.loaded = None
        self.proc.stdin.write(b"fin\n" if command == "terminer" else b"suivant\n")
        await self.proc.stdin.drain()
        self.phase = "finalisation" if command == "terminer" else "scan"

    async def poll(self):
        while True:
            async with self.mutex:
                if self.phase == "attente" or (self.phase == "pret" and not running_job()):
                    pressed = await self.sample()
                    if pressed is False:
                        self.armed = True
                    elif pressed and self.armed:
                        self.armed = False
                        if self.loaded:
                            if self.phase == "attente":
                                await self.resume("suivant")
                            else:
                                await self.start("bouton")
                else:
                    self.sensors.close()
                    self.loaded = None
                    self.armed = False
            await asyncio.sleep(2 if self.hardware_error else .20)

    async def request(self, command):
        action = command["action"]
        async with self.mutex:
            if action == "etat":
                return self.status()
            if self.phase == "attente" and action in ("suivant", "terminer"):
                if action == "suivant":
                    await self.sample()
                    if not self.loaded:
                        raise ValueError(self.hardware_error or "Chargeur vide.")
                await self.resume(action)
            elif self.phase != "pret" or running_job():
                raise ValueError("Travail déjà en cours.")
            elif action in ("choisir", "demarrer"):
                if action == "choisir":
                    mode = command["mode"]
                    if mode not in MODES:
                        raise ValueError("Mode inconnu.")
                    remember(mode)
                    self.mode = mode
                if action == "demarrer" or command.get("si_charge"):
                    await self.sample()
                    if self.loaded:
                        await self.start("commande")
                    elif action == "demarrer" or self.hardware_error:
                        raise ValueError(self.hardware_error or "Chargeur vide.")
            else:
                raise ValueError("Commande indisponible dans cet état.")
            return self.status()


async def serve():
    STATE.mkdir(parents=True, exist_ok=True)
    controller = Controller(Sensors())
    async def handle(reader, writer):
        try:
            request = json.loads(await asyncio.wait_for(reader.readline(), 5))
            reply = await controller.request(request)
        except Exception as exc:
            reply = {"erreur": str(exc)}
        try:
            writer.write(json.dumps(reply).encode()+b"\n")
            await writer.drain()
        finally:
            writer.close()

    path = STATE/"controle.sock"
    path.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle, path=str(path))
    os.chmod(path, 0o600)
    async with server:
        await controller.poll()


async def client(args):
    reader, writer = await asyncio.open_unix_connection(str(STATE/"controle.sock"))
    try:
        writer.write(json.dumps(vars(args)).encode()+b"\n")
        await writer.drain()
        reply = json.loads(await reader.readline())
    finally:
        writer.close()
    if args.json:
        print(json.dumps(reply, ensure_ascii=False))
    else:
        print(reply.get("erreur") or f"{reply['mode']} · {reply['etat']} · chargeur : {reply['charge']}")
        if reply.get("erreur_capteur"):
            print(reply["erreur_capteur"])
        if reply.get("dernier"):
            print(json.dumps(reply["dernier"], ensure_ascii=False))
    return int("erreur" in reply)


if __name__ == "__main__":
    if sys.argv[1:] == ["service"]:
        asyncio.run(serve())
    else:
        parser = argparse.ArgumentParser(prog="scanstation")
        parser.add_argument("action", choices=COMMANDS)
        parser.add_argument("mode", nargs="?", choices=MODES)
        parser.add_argument("--demarrer-si-charge", dest="si_charge", action="store_true")
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args()
        if (args.action == "choisir") != bool(args.mode) or (args.si_charge and args.action != "choisir"):
            parser.error("Utiliser choisir MODE [--demarrer-si-charge] ou une action sans mode.")
        try:
            sys.exit(asyncio.run(client(args)))
        except (OSError, ValueError) as exc:
            msg = f"Service ScanStation indisponible : {exc}"
            print(json.dumps({"erreur": msg}) if args.json else msg)
            sys.exit(1)
