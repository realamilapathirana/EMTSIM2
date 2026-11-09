"""Generate circuits/grid100.net: a 100-node test network for EMTSim, with a drawing.

    python circuits/make_grid100.py        (needs Node.js for gui/layout_to_net.js)

The script places every element on the circuit editor's grid. The netlist is
then produced from that drawing by gui/schematic.js (the editor's own code), so
the file opens in the editor and the drawing and the netlist always agree.
Node numbers are assigned by the editor: left to right, then top to bottom.

build_area() is also used by make_grid1000.py, which joins 10 of these networks.

Network
-------
* Meshed ring of 12 buses (B1..B12), drawn left to right along one line; the
  closing section B12-B1 returns along the top. Each ring section is R + L in
  series (with a node in between) and every ring bus has a line-charging
  capacitor.
* 15 generators above their buses, each on its own terminal node:
    - 12 Norton sources (internal resistance) behind a step-up transformer
      leakage inductance (G1..G12 on B1..B12),
    - 3 ideal grid infeeds behind a transformer inductance (G13..G15 on B1, B5, B9),
    - generator G7 is connected through a breaker instead of a transformer.
  Voltages and angles vary slightly between generators.
* 6 radial feeders hanging below B2, B4, B6, B8, B10 and B11, each with 5 load
  buses built from R and L sections; the load buses have resistive loads, with
  inductive (motor) or capacitive (power factor correction) loads on alternate
  buses.
* A switched 150 uF capacitor bank below ring bus B3.
* 10 uF || 100 ohm to ground on the line side of each ring-tie and feeder
  breaker (terminal stray capacitance and losses), so that interrupting an
  inductive current rings physically instead of causing numerical chatter.

Events
------
    20 ms  bolted fault on feeder 4, bus 3            (F)
    30 ms  feeder 4 breaker trips                     (SW)
    40 ms  capacitor bank energised on B3             (SW)
    45 ms  fault extinguishes                         (F)
    50 ms  ring tie B6-B7 opens                       (SW)
    55 ms  feeder 1 breaker trips                     (SW)
    65 ms  generator G7 breaker trips                 (SW)
    70 ms  feeder 4 recloses onto the healthy feeder  (SW)
    75 ms  feeder 1 recloses                          (SW)
    85 ms  ring tie B6-B7 recloses                    (SW)
    90 ms  ring tie B12-B1 opens                      (SW)
"""
import json
import os
import re
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

NB, P, Y = 12, 24, 20            # buses, horizontal pitch between buses, ring line row (within an area)
X = [14 + P*i for i in range(NB)]  # x of each ring bus (within an area)
AREA_WIDTH = X[-1] + 16 + 2      # rightmost wire of an area is at X[-1] + 16


def num(x):
    return "%.6g" % x


class Drawing:
    """Components and wires in the circuit editor's format."""

    def __init__(self, phases=1, settings=None):
        self.comps, self.wires = [], []
        self.phases = phases          # 3: a three-phase drawing (components R3, L3, C3, V3, SW3, F3)
        self.settings = settings or {}  # run settings: {"dt": "50u", "tstop": "200m"}

    def add(self, ctype, name, x, y, rot=0, /, **params):   # positional-only, so params may be called x, y
        self.comps.append({"type": ctype, "name": name, "x": x, "y": y, "rot": rot,
                           "params": {k: (num(v) if isinstance(v, float) else str(v)) for k, v in params.items()}})

    def gnd(self, x, y):
        self.comps.append({"type": "GND", "name": "GND", "x": x, "y": y, "rot": 0, "params": {}})

    def wire(self, *pts):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            self.wires.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

    def shunt_right(self, kind, name, x, y, stub, **params):
        """Element from node (x, y) to ground, drawn to the right after a wire stub."""
        self.wire((x, y), (x + stub, y))
        self.add(kind, name, x + stub, y, 0, **params)
        self.gnd(x + stub + 4, y)

    def shunt_left(self, kind, name, x, y, stub, **params):
        self.wire((x, y), (x - stub, y))
        self.add(kind, name, x - stub, y, 180, **params)
        self.gnd(x - stub - 4, y)

    def shunt_down(self, kind, name, x, y, **params):
        self.add(kind, name, x, y, 90, **params)
        self.gnd(x, y + 4)


def build_area(d, ox=0, oy=0, prefix="", events=True, angle_offset=0.0):
    """Draw one 100-node network with its top-left corner offset by (ox, oy).

    prefix       : prepended to every element name (e.g. "A3.")
    events       : False -> no fault, and the switches never operate
    angle_offset : added to every generator angle (degrees)
    """
    def at(x, y):
        return x + ox, y + oy

    def add(kind, name, x, y, rot=0, **params):
        if not events and kind == "SW":
            params["times"] = ""
        d.add(kind, prefix + name, *at(x, y), rot, **params)

    def gnd(x, y):
        d.gnd(*at(x, y))

    def wire(*pts):
        d.wire(*[at(*p) for p in pts])

    def shunt(side, kind, name, x, y, stub=None, **params):
        if not events and kind == "SW":
            params["times"] = ""
        if side == "down":
            d.shunt_down(kind, prefix + name, *at(x, y), **params)
        elif side == "right":
            d.shunt_right(kind, prefix + name, *at(x, y), stub, **params)
        else:
            d.shunt_left(kind, prefix + name, *at(x, y), stub, **params)

    # ------------------------------------------------------------ ring
    for i in range(NB):
        a = X[i]
        name = "B%d-B%d" % (i + 1, (i + 1) % NB + 1)
        shunt("down", "C", "C_B%d" % (i + 1), a - 9, Y, value=8e-6)    # line charging, on the incoming wire
        wire((a, Y), (a + 2, Y))
        if i == 5:      # B6-B7 tie: opens at 50 ms, recloses at 85 ms
            add("SW", "SW_" + name, a + 2, Y, 0, state="closed", times="0.05 0.085")
        elif i == 11:   # B12-B1 tie: opens at 90 ms
            add("SW", "SW_" + name, a + 2, Y, 0, state="closed", times="0.09")
        else:
            add("R", "R_" + name, a + 2, Y, 0, value=0.4 + 0.05*(i % 3))
        wire((a + 6, Y), (a + 10, Y))
        if i in (5, 11):  # breaker terminal stray capacitance and damping on the line side
            shunt("down", "C", "Cb_" + name, a + 6, Y, value=10e-6)
            shunt("down", "R", "Rb_" + name, a + 10, Y, value=100.0)
        add("L", "L_" + name, a + 10, Y, 0, value=4e-3 + 0.5e-3*(i % 4))
        if i < NB - 1:
            wire((a + 14, Y), (X[i + 1], Y))
        else:         # return to B1 along the top
            wire((a + 14, Y), (a + 16, Y), (a + 16, 6), (X[0] - 12, 6), (X[0] - 12, Y), (X[0], Y))

    # ------------------------------------------------------------ generators
    gen_bus = list(range(NB)) + [0, 4, 8]
    for g, bi in enumerate(gen_bus):
        x = X[bi]
        mag = 325.0*(1.0 + 0.01*((g % 5) - 2))
        ang = (-12.0 + 2.0*g if g < 12 else -5.0*(g - 12)) + angle_offset
        src = dict(mag=mag, angle=ang, freq=50.0, r=(0.3 if g < 12 else ""))
        if g < 12:      # terminal (x, 10), source to its left, transformer down to the bus
            add("V", "G%d" % (g + 1), x - 4, 10, 0, **src)
            gnd(x - 4, 10)
            if g == 6:  # G7 has a breaker instead of a transformer: trips at 65 ms
                add("SW", "SW_G7", x, 10, 90, state="closed", times="0.065")
            else:
                add("L", "T_G%d" % (g + 1), x, 10, 90, value=3e-3)
            wire((x, 14), (x, Y))
        else:           # second (ideal) infeed: terminal (x+4, 10), source to its right
            add("V", "G%d" % (g + 1), x + 8, 10, 180, **src)
            gnd(x + 8, 10)
            add("L", "T_G%d" % (g + 1), x + 4, 10, 90, value=2e-3)
            wire((x + 4, 14), (x + 4, 16), (x, 16))

    # ------------------------------------------------------------ feeders
    feeder_from = [1, 3, 5, 7, 9, 10]
    for fdr, bi in enumerate(feeder_from):
        x = X[bi]
        for k in range(5):
            top, mid, load = Y + 8*k, Y + 8*k + 4, Y + 8*k + 8
            tag = "F%d_%d" % (fdr + 1, k + 1)
            if k == 0 and fdr in (0, 3):   # feeder breakers: feeder 1 trips 55 / recloses 75 ms, feeder 4 30 / 70 ms
                add("SW", "SW_F%d" % (fdr + 1), x, top, 90, state="closed",
                    times="0.055 0.075" if fdr == 0 else "0.03 0.07")
                shunt("right", "C", "Cb_F%d" % (fdr + 1), x, mid, 7, value=10e-6)
                shunt("left", "R", "Rb_F%d" % (fdr + 1), x, mid, 3, value=100.0)
            else:
                add("R", "R_" + tag, x, top, 90, value=0.25 + 0.05*k)
            add("L", "L_" + tag, x, mid, 90, value=1.5e-3 + 0.25e-3*k)
            shunt("right", "R", "Rld_" + tag, x, load, 3, value=80.0 + 15.0*k + 5.0*fdr)
            if k % 2 == 0:
                shunt("left", "L", "M_" + tag, x, load, 3, value=0.4 + 0.05*fdr)    # motor load
            else:
                shunt("left", "C", "Cpf_" + tag, x, load, 3, value=12e-6)          # power factor correction
            if fdr == 3 and k == 2 and events:   # the fault: feeder 4, bus 3, 20 ms to 45 ms
                wire((x - 1, load), (x - 1, load + 3))
                add("F", "FAULT", x - 1, load + 3, 180, t_apply="0.02", t_clear="0.045")
                gnd(x - 5, load + 3)

    # ------------------------------------------------------------ capacitor bank on B3
    x = X[2]
    add("SW", "SW_CB", x, Y, 90, state="open", times="0.04")
    wire((x, Y + 4), (x, Y + 8))
    shunt("right", "C", "C_CB", x, Y + 4, 6, value=150e-6)
    shunt("right", "R", "R_CB", x, Y + 8, 6, value=1.0e4)


def netlist_from_drawing(d, title, allow_warnings=False):
    """Netlist text for a drawing, produced by the editor's own code (gui/layout_to_net.js)."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"v": 1, "phases": d.phases, "settings": d.settings, "components": d.comps, "wires": d.wires}, f)
        tmp = f.name
    try:
        p = subprocess.run(["node", os.path.join(ROOT, "gui", "layout_to_net.js"), tmp, title],
                           capture_output=True, text=True)
    finally:
        os.remove(tmp)
    if p.returncode != 0 or (p.stderr.strip() and not allow_warnings):
        raise SystemExit("The drawing has problems:\n" + p.stderr)
    text = p.stdout
    kinds = [l.split()[0] for l in text.splitlines() if l and not l.startswith("#")]
    counts = {k: kinds.count(k) for k in ("R", "L", "C", "V", "SW", "F")}
    # header line "# 100 nodes, ..." or, for three-phase drawings, "# 12 nodes (4 three-phase nodes), ..."
    nodes = int(next(m.group(1) for m in (re.match(r"# (\d+) nodes\b", l) for l in text.splitlines()) if m))
    return text, nodes, counts


def write_netlist(path, text, doc_lines):
    header = doc_lines + ["#", ""]
    with open(path, "w", newline="\n") as f:
        f.write("\n".join(header) + text)


def doc_comment(doc, first_lines):
    body = doc.split("Network\n-------\n")[1]
    return first_lines + ["#"] + ["# " + l if l else "#" for l in body.rstrip().splitlines()]


if __name__ == "__main__":
    out = os.path.join(HERE, "grid100.net")
    d = Drawing()
    build_area(d)
    text, nodes, counts = netlist_from_drawing(d, "100-node test network")
    assert nodes == 100, nodes
    assert counts["V"] == 15 and counts["SW"] == 6 and counts["F"] == 1, counts
    write_netlist(out, text, doc_comment(__doc__, [
        "# 100-node test network for EMTSim, generated by circuits/make_grid100.py.",
        "# Open it in the circuit editor (gui.bat) to see the drawing."]))
    print("Wrote %s: %d nodes, %d elements %s" % (os.path.relpath(out, ROOT), nodes, sum(counts.values()), counts))
