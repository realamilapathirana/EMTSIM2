"""Local web server for the EMTSim circuit editor.

    python gui/server.py            # opens http://127.0.0.1:8765 in your browser
    python gui/server.py --no-browser --port 9000

Serves the editor (gui/index.html) and a small JSON API:
    GET  /api/circuits             list of .net files in circuits/
    GET  /api/circuit?name=x.net   text of one file
    POST /api/save   {name, text}  save a netlist into circuits/
    POST /api/run    {text, engine: "cpp" | "python" | "both"}
                                   run the simulator(s) and return node voltages

Only listens on 127.0.0.1 (this computer). Uses the Python standard library only;
the Python simulator itself needs numpy, scipy and matplotlib.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

GUI = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(GUI)
CIRCUITS = os.path.join(ROOT, "circuits")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/schematic.js": ("schematic.js", "text/javascript; charset=utf-8")}


def find_cpp_exe():
    for rel in ("build/emtsim.exe", "build/Release/emtsim.exe", "build/emtsim", "build/Release/emtsim"):
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            return p
    return None


def run_cpp(net_path, work):
    exe = find_cpp_exe()
    if not exe:
        return {"error": "The C++ simulator is not built yet. Run build.bat (or cmake) first."}
    p = subprocess.run([exe, net_path], cwd=work, capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        return {"error": (p.stderr or p.stdout).strip()[-4000:]}
    with open(os.path.join(work, "results.csv"), newline="") as f:
        rows = list(csv.reader(f))
    names = rows[0][1:]
    data = [[float(x) for x in r] for r in rows[1:] if r]
    faults, switches = [], []
    with open(os.path.join(work, "events.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if r["type"] == "fault":
                faults.append([float(r["t_start"]), float(r["t_end"]) if r["t_end"] else None])
            else:
                switches.append(float(r["t_start"]))
    sim_ms = next((float(l.split(":")[1].split()[0]) for l in p.stdout.splitlines() if l.startswith("Simulation time:")), None)
    cnames, I = [], []
    cpath = os.path.join(work, "currents.csv")
    if os.path.isfile(cpath):   # branch currents (and machine speed, angle, power, torque)
        with open(cpath, newline="") as f:
            crow = list(csv.reader(f))
        cnames = crow[0][1:]
        cdata = [[float(x) for x in r[1:]] for r in crow[1:] if r]
        I = [[r[k] for r in cdata] for k in range(len(cnames))]
    return {"names": names, "t": [r[0] for r in data], "V": [[r[k + 1] for r in data] for k in range(len(names))],
            "cnames": cnames, "I": I,
            "events": {"faults": faults, "switches": switches}, "sim_ms": sim_ms,
            "log": "\n".join(l for l in p.stdout.splitlines() if l.startswith("t = ") or l.startswith("Warning"))}


def run_python(net_path):
    p = subprocess.run([sys.executable, os.path.join(GUI, "run_python.py"), net_path],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (p.stderr or p.stdout or "Python simulator failed").strip()[-4000:]}


def simulate(text, engine):
    with tempfile.TemporaryDirectory(prefix="emtsim_") as work:
        net_path = os.path.join(work, "circuit.net")
        with open(net_path, "w", newline="\n") as f:
            f.write(text)
        out = {}
        if engine in ("cpp", "both"):
            out["cpp"] = run_cpp(net_path, work)
        if engine in ("python", "both"):
            out["python"] = run_python(net_path)
    a, b = out.get("cpp"), out.get("python")
    if a and b and "error" not in a and "error" not in b and len(a["V"]) == len(b["V"]):
        diff = max((abs(x - y) for va, vb in zip(a["V"], b["V"]) for x, y in zip(va, vb)), default=0.0)
        peak = max((abs(x) for v in b["V"] for x in v), default=0.0)
        out["compare"] = {"max_diff": diff, "peak": peak,
                          "speedup": (b["sim_ms"] / a["sim_ms"]) if a.get("sim_ms") else None}
    # The comparison above uses full precision; for plotting, 7 significant digits are plenty
    # and roughly halve the size of the response for large networks.
    for r in (a, b):
        for key in ("V", "I"):
            if r and key in r:
                r[key] = [[float("%.7g" % x) for x in v] for v in r[key]]
    return out


def safe_name(name):
    name = os.path.basename(str(name or "").strip())
    if not name.endswith(".net"):
        name += ".net"
    if not re.fullmatch(r"[A-Za-z0-9_.\- ]+\.net", name):
        raise ValueError("Use only letters, digits, spaces, '-', '_' and '.' in the file name.")
    return name


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in STATIC:
            fname, ctype = STATIC[url.path]
            with open(os.path.join(GUI, fname), "rb") as f:
                return self.send(200, f.read(), ctype)
        if url.path == "/api/circuits":
            files = []
            for n in sorted(os.listdir(CIRCUITS)):
                if n.endswith(".net"):
                    with open(os.path.join(CIRCUITS, n), encoding="utf-8") as f:
                        files.append({"name": n, "drawing": any(l.startswith("#@layout ") for l in f)})
            return self.send(200, {"files": files})
        if url.path == "/api/circuit":
            try:
                name = safe_name(parse_qs(url.query).get("name", [""])[0])
                with open(os.path.join(CIRCUITS, name), encoding="utf-8") as f:
                    return self.send(200, {"name": name, "text": f.read()})
            except (OSError, ValueError) as e:
                return self.send(404, {"error": str(e)})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.send(400, {"error": "invalid JSON"})
        path = urlparse(self.path).path
        try:
            if path == "/api/save":
                name = safe_name(body.get("name"))
                with open(os.path.join(CIRCUITS, name), "w", encoding="utf-8", newline="\n") as f:
                    f.write(body.get("text", ""))
                return self.send(200, {"saved": "circuits/" + name})
            if path == "/api/run":
                engine = body.get("engine", "cpp")
                if engine not in ("cpp", "python", "both"):
                    return self.send(400, {"error": "engine must be cpp, python or both"})
                return self.send(200, simulate(body.get("text", ""), engine))
        except subprocess.TimeoutExpired:
            return self.send(500, {"error": "The simulation took too long and was stopped."})
        except (OSError, ValueError) as e:
            return self.send(400, {"error": str(e)})
        self.send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser(description="EMTSim circuit editor")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    server = None
    for port in range(args.port, args.port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit("No free port found near %d" % args.port)
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    print("EMTSim circuit editor running at %s" % url)
    print("C++ simulator: %s" % (find_cpp_exe() or "not built (run build.bat)"))
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
