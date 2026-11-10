"""Build "Tiny book of EMT simulation" (docs/book/TinyBookOfEMT.pdf).

    python docs/book/make_book.py            figures + HTML + PDF (PDF printed with Microsoft Edge)
    python docs/book/make_book.py --no-pdf   figures + HTML only

Every number in the book is computed here by a small re-implementation of the EMTSim time
loop (the same companion models, the same order of operations), and checked against the
C++ solver (build/emtsim.exe) when it has been built.
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle, Polygon, FancyBboxPatch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIG = os.path.join(HERE, "fig")
NETS = os.path.join(HERE, "circuits")

INK = "#1a1a1a"
ACCENT = "#C55A11"      # simulation results and numbers (the orange-brown of the neural network book)
GREY = "#8a8a8a"
FAULT = "#f3dcdc"

plt.rcParams.update({
    "font.family": "Georgia", "font.size": 11, "svg.fonttype": "path",
    "axes.edgecolor": "#555", "axes.linewidth": 0.8, "axes.labelcolor": INK,
    "xtick.color": "#444", "ytick.color": "#444", "axes.spines.top": False, "axes.spines.right": False,
    "mathtext.fontset": "cm",
})


# ============================================================ a tiny EMT solver (same steps as EMTSim)
class Circuit:
    """Elements: ("R"|"L"|"C", a, b, value, name), ("V", node, peak, freq, name) ideal source to ground,
    ("SW", a, b, closed(t) -> bool, name) with Ron = 0.01, Roff = 1e6 as in EMTSim."""

    def __init__(self, n, elements, dt):
        self.n, self.el, self.dt = n, elements, dt
        self.known = [e[1] for e in elements if e[0] == "V"]
        self.unknown = [k for k in range(1, n + 1) if k not in self.known]
        self.state = {e[-1]: {"I": 0.0, "V": 0.0, "h": 0.0} for e in elements}

    def reff(self, e, t):
        k = e[0]
        if k == "R":
            return e[3]
        if k == "L":
            return 2 * e[3] / self.dt
        if k == "C":
            return self.dt / (2 * e[3])
        if k == "SW":
            return 0.01 if e[3](t) else 1.0e6

    def G(self, t):
        G = np.zeros((self.n + 1, self.n + 1))
        for e in self.el:
            if e[0] == "V":
                continue
            g = 1 / self.reff(e, t)
            a, b = e[1], e[2]
            G[a, a] += g; G[b, b] += g; G[a, b] -= g; G[b, a] -= g
        return G[1:, 1:]

    def step(self, t):
        """One step at time t. Returns dict with everything the book prints."""
        G = self.G(t)
        inj = np.zeros(self.n + 1)
        hist = {}
        for e in self.el:
            s = self.state[e[-1]]
            if e[0] == "L":
                s["h"] = s["I"] + s["V"] / self.reff(e, t)
            elif e[0] == "C":
                s["h"] = -s["I"] - s["V"] / self.reff(e, t)
            else:
                s["h"] = 0.0
            if e[0] in "LC":
                hist[e[-1]] = s["h"]
                inj[e[1]] -= s["h"]; inj[e[2]] += s["h"]
        inj = inj[1:]
        U = [k - 1 for k in self.unknown]
        K = [k - 1 for k in self.known]
        vK = np.array([e[2] * math.cos(2 * math.pi * e[3] * t) for e in self.el if e[0] == "V"])
        rhs = inj[U] - G[np.ix_(U, K)] @ vK
        vU = np.linalg.solve(G[np.ix_(U, U)], rhs)
        v = np.zeros(self.n + 1)
        v[[k + 1 for k in K]] = vK
        v[[k + 1 for k in U]] = vU
        cur = {}
        for e in self.el:
            s = self.state[e[-1]]
            if e[0] == "V":
                continue
            s["V"] = v[e[1]] - v[e[2]]
            s["I"] = s["V"] / self.reff(e, t) + s["h"]
            cur[e[-1]] = s["I"]
        return {"t": t, "v": v, "i": cur, "hist": hist, "G": G, "rhs": rhs, "inj": inj, "vK": vK}

    def run(self, tstop):
        out, t = [], 0.0
        nsteps = int(round(tstop / self.dt))
        for k in range(1, nsteps + 1):
            out.append(self.step(k * self.dt))
        return out


def rl_circuit(dt, opens=None):
    if opens is None:
        return Circuit(2, [("V", 1, 10.0, 0.0, "BATTERY"), ("R", 1, 2, 1.0, "R"), ("L", 2, 0, 1e-3, "L")], dt)
    return Circuit(3, [("V", 1, 10.0, 0.0, "BATTERY"), ("SW", 1, 2, lambda t: t < opens - 1e-12, "SWITCH"),
                       ("R", 2, 3, 1.0, "R"), ("L", 3, 0, 1e-3, "L")], dt)


def network(dt, fault=None):
    el = [("V", 1, 100.0, 50.0, "SOURCE"), ("R", 1, 2, 1.0, "R1"), ("L", 2, 3, 0.01, "L"),
          ("C", 3, 0, 10e-6, "C"), ("R", 3, 0, 100.0, "LOAD")]
    if fault:
        el.append(("SW", 3, 0, lambda t: fault[0] - 1e-12 <= t < fault[1] - 1e-12, "FAULT"))
    return Circuit(3, el, dt)


# ------------------------------------------------------------ check against the C++ solver
def emtsim(netfile):
    exe = os.path.join(ROOT, "build", "emtsim.exe" if os.name == "nt" else "emtsim")
    if not os.path.exists(exe):
        return None
    d = tempfile.mkdtemp()
    try:
        subprocess.run([exe, netfile], cwd=d, check=True, capture_output=True)
        v = np.loadtxt(os.path.join(d, "results.csv"), delimiter=",", skiprows=1)
        with open(os.path.join(d, "currents.csv")) as f:
            names = f.readline().strip().split(",")
        c = np.loadtxt(os.path.join(d, "currents.csv"), delimiter=",", skiprows=1)
        return v, dict(zip(names, c.T))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def check(name, steps, current_names):
    res = emtsim(os.path.join(NETS, name))
    if res is None:
        print("  (build/emtsim.exe not found: %s not checked)" % name)
        return
    v, c = res
    mine_v = np.array([s["v"][1:] for s in steps])
    dv = np.abs(mine_v - v[:, 1:]).max()
    di = max(np.abs(np.array([s["i"][n] for s in steps]) - c[n]).max() for n in current_names)
    scale = max(1.0, np.abs(v[:, 1:]).max())
    ok = dv < 1e-9 * scale and di < 1e-9 * scale
    print("  %-18s EMTSim agrees: max difference %.1e V, %.1e A  %s" % (name, dv, di, "OK" if ok else "MISMATCH"))
    if not ok:
        raise SystemExit("book numbers do not match EMTSim for " + name)


# ============================================================ schematic drawing
LW = 1.6


def _frame(p1, p2, body):
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    d = p2 - p1
    L = np.hypot(*d)
    u = d / L
    n = np.array([-u[1], u[0]])
    a = p1 + u * (L - body) / 2
    T = lambda s, w: a + u * s + n * w
    return p1, p2, a, a + u * body, u, n, T


def line(ax, *pts, **kw):
    pts = np.asarray(pts, float)
    ax.plot(pts[:, 0], pts[:, 1], color=kw.get("color", INK), lw=kw.get("lw", LW), solid_capstyle="round",
            zorder=kw.get("zorder", 2))


def resistor(ax, p1, p2, body=1.2):
    p1, p2, a, b, u, n, T = _frame(p1, p2, body)
    s = np.linspace(0, body, 14)
    w = np.zeros_like(s)
    w[1:-1] = [0.17 if k % 2 else -0.17 for k in range(1, len(s) - 1)]
    line(ax, p1, a); line(ax, b, p2)
    line(ax, *[T(si, wi) for si, wi in zip(s, w)])


def inductor(ax, p1, p2, body=1.2, side=1):
    p1, p2, a, b, u, n, T = _frame(p1, p2, body)
    line(ax, p1, a); line(ax, b, p2)
    r = body / 8
    pts = []
    for k in range(4):
        c = (2 * k + 1) * r
        for th in np.linspace(math.pi, 0, 16):
            pts.append(T(c + r * math.cos(th), side * r * 1.3 * math.sin(th)))
    line(ax, *pts)


def capacitor(ax, p1, p2, gap=0.14, half=0.32):
    p1, p2, a, b, u, n, T = _frame(p1, p2, 0)
    m = (p1 + p2) / 2
    line(ax, p1, m - u * gap); line(ax, m + u * gap, p2)
    line(ax, m - u * gap - n * half, m - u * gap + n * half, lw=2.2)
    line(ax, m + u * gap - n * half, m + u * gap + n * half, lw=2.2)


def vsource(ax, p1, p2, kind="dc", r=0.42):
    """p1 = minus terminal, p2 = plus terminal"""
    p1, p2, a, b, u, n, T = _frame(p1, p2, 2 * r)
    c = (p1 + p2) / 2
    line(ax, p1, c - u * r); line(ax, c + u * r, p2)
    ax.add_patch(Circle(c, r, fill=False, ec=INK, lw=LW, zorder=2))
    if kind == "ac":
        s = np.linspace(-0.6, 0.6, 40) * r
        pts = [c + n * si + u * 0.35 * r * math.sin(si / r / 0.6 * math.pi) for si in s]
        line(ax, *pts, lw=1.3)
    else:
        ax.text(*(c + u * r * 0.45), "+", ha="center", va="center", fontsize=11, color=INK)
        ax.text(*(c - u * r * 0.5), "−", ha="center", va="center", fontsize=11, color=INK)


def isource(ax, p1, p2, r=0.36):
    """arrow from p1 to p2"""
    p1, p2, a, b, u, n, T = _frame(p1, p2, 2 * r)
    c = (p1 + p2) / 2
    line(ax, p1, c - u * r); line(ax, c + u * r, p2)
    ax.add_patch(Circle(c, r, fill=False, ec=INK, lw=LW, zorder=2))
    ax.annotate("", xy=c + u * r * 0.7, xytext=c - u * r * 0.7,
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4, mutation_scale=11))


def switch(ax, p1, p2, closed=False, body=1.0):
    p1, p2, a, b, u, n, T = _frame(p1, p2, body)
    line(ax, p1, a); line(ax, b, p2)
    for q in (a, b):
        ax.add_patch(Circle(q, 0.07, fc="white", ec=INK, lw=1.4, zorder=3))
    tip = b if closed else a + u * body * 0.92 + n * 0.45
    line(ax, a, tip)


def ground(ax, p, down=0.35):
    p = np.asarray(p, float)
    line(ax, p, p - [0, down])
    for k, w in enumerate((0.32, 0.2, 0.08)):
        y = p[1] - down - k * 0.1
        line(ax, (p[0] - w, y), (p[0] + w, y), lw=1.4)


def node(ax, p, label=None, dx=0.0, dy=0.32):
    ax.add_patch(Circle(p, 0.07, fc=INK, ec=INK, zorder=4))
    if label is not None:
        q = (p[0] + dx, p[1] + dy)
        ax.add_patch(Circle(q, 0.17, fc=INK, ec=INK, zorder=4))
        ax.text(*q, str(label), color="white", ha="center", va="center", fontsize=8.5, zorder=5, fontweight="bold")


def text(ax, p, s, **kw):
    kw.setdefault("ha", "center"); kw.setdefault("va", "center")
    kw.setdefault("fontsize", 11); kw.setdefault("color", INK)
    ax.text(p[0], p[1], s, **kw)


def canvas(w, h, xlim, ylim):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.set_aspect("equal"); ax.axis("off")
    fig.subplots_adjust(0, 0, 1, 1)
    return fig, ax


def save(fig, name):
    fig.savefig(os.path.join(FIG, name), transparent=False, facecolor="white")
    plt.close(fig)


# ============================================================ figures
def fig_cover():
    """Line art for the cover tile: a steady sine wave, a switching transient, and the time steps."""
    fig, ax = plt.subplots(figsize=(2.3, 5.4))
    fig.subplots_adjust(0, 0, 1, 1)
    ax.axis("off")
    t = np.linspace(0, 1, 2000)
    # vertical "time" axis going down the tile, waveform swinging left-right
    y = 1 - t
    env = np.where(t < 0.38, 0, np.exp(-(t - 0.38) * 7))
    x = 0.55 * np.sin(2 * np.pi * 3 * t) * (1 - 0.6 * (t >= 0.38)) + 0.9 * env * np.sin(2 * np.pi * 26 * (t - 0.38))
    ax.plot(x, y, color=INK, lw=1.5)
    ts = t[::60]
    xs = np.interp(ts, t, x)
    ax.scatter(xs, 1 - ts, s=7, color=INK, zorder=3)
    for k in np.linspace(0, 1, 34):
        ax.plot([-1.25, -1.1], [k, k], color=INK, lw=0.6)
    ax.plot([-1.175, -1.175], [0, 1], color=INK, lw=0.6)
    ax.set_xlim(-1.35, 1.25); ax.set_ylim(-0.04, 1.04)
    save(fig, "cover.svg")


def fig_photo_movie():
    fig = plt.figure(figsize=(6.6, 2.5))
    # the photo: one phasor
    ax = fig.add_axes([0.0, 0.08, 0.26, 0.84]); ax.set_aspect("equal"); ax.axis("off")
    ax.add_patch(FancyBboxPatch((-1.2, -1.2), 2.4, 2.4, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fill=False, ec=INK, lw=1.4))
    ax.add_patch(Circle((0, 0), 0.85, fill=False, ec=GREY, lw=0.8, ls="--"))
    ax.annotate("", xy=(0.6, 0.6), xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=ACCENT, lw=2, mutation_scale=14))
    ax.text(0, -1.5, "Phasor: one photo", ha="center", fontsize=10.5, fontweight="bold")
    ax.set_xlim(-1.3, 1.3); ax.set_ylim(-1.75, 1.3)
    # the movie: a film strip
    ax = fig.add_axes([0.3, 0.08, 0.7, 0.84]); ax.axis("off")
    nf = 6
    W, H = 1.0, 0.8
    ax.add_patch(plt.Rectangle((-0.1, -0.25), nf * (W + 0.1) + 0.1, H + 0.5, fc=INK, ec=INK))
    for k in range(nf * 3 + 1):
        ax.add_patch(plt.Rectangle((-0.06 + k * (W + 0.1) / 3, H + 0.1), 0.12, 0.08, fc="white", ec="white"))
        ax.add_patch(plt.Rectangle((-0.06 + k * (W + 0.1) / 3, -0.18), 0.12, 0.08, fc="white", ec="white"))
    tt = np.linspace(0, 1, 300)
    wave = lambda x: np.where(x < 0.3, 0.0, np.sin(2 * np.pi * 2.2 * (x - 0.3)) * (1 - np.exp(-(x - 0.3) * 9))
                              + 0.6 * np.exp(-(x - 0.3) * 7) * np.sin(2 * np.pi * 9 * (x - 0.3)))
    for k in range(nf):
        x0 = k * (W + 0.1)
        ax.add_patch(plt.Rectangle((x0, 0), W, H, fc="white", ec="white"))
        tk = (k + 1) / nf
        m = tt <= tk
        ax.plot(x0 + 0.05 + 0.9 * tt[m], H / 2 + 0.3 * wave(tt[m]), color=GREY, lw=0.9)
        ax.plot(x0 + 0.05 + 0.9 * tk, H / 2 + 0.3 * wave(np.array([tk]))[0], "o", color=ACCENT, ms=4.5)
        ax.text(x0 + W / 2, -0.47, ["t = Δt", "2Δt", "3Δt", "4Δt", "5Δt", "6Δt"][k], ha="center", fontsize=9.5)
    ax.text(nf * (W + 0.1) / 2, -0.82, "EMT simulation: a movie, one frame every Δt", ha="center",
            fontsize=10.5, fontweight="bold")
    ax.set_xlim(-0.15, nf * (W + 0.1) + 0.05); ax.set_ylim(-1.0, H + 0.3)
    save(fig, "photo_movie.svg")


def fig_rl():
    fig, ax = canvas(5.6, 2.9, (-1.9, 9.4), (-1.2, 4.4))
    vsource(ax, (0, 0), (0, 3))
    switch(ax, (0, 3), (3, 3), closed=False)
    resistor(ax, (3, 3), (6, 3))
    line(ax, (6, 3), (8, 3))
    inductor(ax, (8, 3), (8, 0))
    line(ax, (0, 0), (8, 0))
    ground(ax, (4, 0))
    node(ax, (0, 3), 1, dy=0.35); node(ax, (6, 3), 2, dy=0.35)
    text(ax, (-0.55, 1.5), "V\n10 V", ha="right", fontsize=10)
    text(ax, (1.5, 3.75), "switch closes\nat t = 0", fontsize=9.5)
    text(ax, (4.5, 3.6), "R = 1 Ω", fontsize=10)
    text(ax, (8.5, 1.5), "L\n1 mH", ha="left", fontsize=10)
    ax.annotate("", xy=(7.6, 3.25), xytext=(6.8, 3.25), arrowprops=dict(arrowstyle="-|>", color=ACCENT, lw=1.4))
    text(ax, (7.2, 3.6), "i", color=ACCENT, fontsize=12, style="italic")
    save(fig, "rl_circuit.svg")


def fig_trapezoid():
    fig, ax = plt.subplots(figsize=(3.4, 2.3))
    t = np.linspace(0, 1, 200)
    v = 0.3 + 0.75 * t + 0.12 * np.sin(5 * t)
    ax.plot(t, v, color=INK, lw=1.6)
    a, b = 0.25, 0.75
    va, vb = np.interp([a, b], t, v)
    ax.add_patch(Polygon([(a, 0), (a, va), (b, vb), (b, 0)], fc=ACCENT, alpha=0.22, ec=ACCENT, lw=1.2))
    m = (t >= a) & (t <= b)
    ax.fill_between(t[m], np.interp(t[m], [a, b], [va, vb]), v[m], color=GREY, alpha=0.3, lw=0)
    ax.plot([a, b], [va, vb], color=ACCENT, lw=1.4)
    ax.set_xticks([a, b]); ax.set_xticklabels(["t − Δt", "t"])
    ax.set_yticks([va, vb]); ax.set_yticklabels(["v(t − Δt)", "v(t)"])
    ax.set_ylim(0, 1.25); ax.set_xlim(0, 1)
    ax.text((a + b) / 2, 0.2, "area ≈ Δt × (average\nof the two heights)", ha="center", fontsize=9)
    fig.tight_layout()
    save(fig, "trapezoid.svg")


def fig_companion():
    fig, ax = canvas(6.4, 4.1, (-0.6, 13.4), (-0.9, 7.6))
    # inductor
    for y0, kind in ((4.3, "L"), (0.0, "C")):
        node(ax, (0, y0 + 2.6)); node(ax, (0, y0))
        text(ax, (0, y0 + 2.95), "k", style="italic"); text(ax, (0, y0 - 0.38), "m", style="italic")
        if kind == "L":
            inductor(ax, (0, y0 + 2.6), (0, y0))
            text(ax, (0.55, y0 + 1.3), "L", ha="left", style="italic", fontsize=12)
        else:
            capacitor(ax, (0, y0 + 2.6), (0, y0))
            text(ax, (0.55, y0 + 1.3), "C", ha="left", style="italic", fontsize=12)
        ax.annotate("", xy=(3.6, y0 + 1.3), xytext=(1.9, y0 + 1.3),
                    arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.6, mutation_scale=16))
        text(ax, (2.75, y0 + 1.75), "one time step", fontsize=8.5, color="#444")
        x1, x2 = 5.2, 7.6
        node(ax, (6.4, y0 + 2.6)); node(ax, (6.4, y0))
        text(ax, (6.4, y0 + 2.95), "k", style="italic"); text(ax, (6.4, y0 - 0.38), "m", style="italic")
        line(ax, (x1, y0 + 2.6), (x2, y0 + 2.6)); line(ax, (x1, y0), (x2, y0))
        resistor(ax, (x1, y0 + 2.6), (x1, y0), body=1.1)
        isource(ax, (x2, y0 + 2.6), (x2, y0))
        if kind == "L":
            text(ax, (x2 + 0.6, y0 + 1.75), r"$R_L = 2L\,/\,\Delta t$", ha="left", fontsize=11)
            text(ax, (x2 + 0.6, y0 + 0.85), r"$I_{\rm hist}(t) = i(t-\Delta t) + v(t-\Delta t)\,/\,R_L$", ha="left", fontsize=11)
        else:
            text(ax, (x2 + 0.6, y0 + 1.75), r"$R_C = \Delta t\,/\,2C$", ha="left", fontsize=11)
            text(ax, (x2 + 0.6, y0 + 0.85), r"$I_{\rm hist}(t) = -i(t-\Delta t) - v(t-\Delta t)\,/\,R_C$", ha="left", fontsize=11)
        text(ax, (x1 + 0.45, y0 + 1.3), r"$R_%s$" % kind, ha="left", fontsize=11)
    save(fig, "companion.svg")


def fig_rl_companion():
    fig, ax = canvas(5.8, 2.6, (-1.9, 10.2), (-1.2, 3.8))
    vsource(ax, (0, 0), (0, 3))
    resistor(ax, (0, 3), (4, 3))
    line(ax, (4, 3), (8.4, 3))
    resistor(ax, (6.2, 3), (6.2, 0), body=1.1)
    isource(ax, (8.4, 3), (8.4, 0))
    line(ax, (0, 0), (8.4, 0))
    ground(ax, (3, 0))
    node(ax, (0, 3), 1, dy=0.35); node(ax, (4, 3), 2, dy=0.35)
    text(ax, (-0.55, 1.5), "V\n10 V", ha="right", fontsize=10)
    text(ax, (2, 3.55), "R = 1 Ω", fontsize=10)
    text(ax, (6.65, 1.5), "$R_L$\n20 Ω", ha="left", fontsize=10)
    text(ax, (8.95, 1.5), r"$I_{\rm hist}$", ha="left", fontsize=11)
    ax.add_patch(FancyBboxPatch((5.35, -0.45), 4.55, 3.9, boxstyle="round,pad=0,rounding_size=0.25",
                                fill=False, ec=ACCENT, lw=1.1, ls="--"))
    text(ax, (7.6, -0.8), "the inductor, for one time step", fontsize=9, color=ACCENT)
    save(fig, "rl_companion.svg")


def fig_network():
    fig, ax = canvas(6.4, 2.7, (-2.4, 13.2), (-1.3, 4.3))
    vsource(ax, (0, 0), (0, 3), kind="ac")
    resistor(ax, (0, 3), (3.4, 3))
    inductor(ax, (3.4, 3), (7.2, 3))
    line(ax, (7.2, 3), (11.5, 3))
    capacitor(ax, (8.8, 3), (8.8, 0))
    resistor(ax, (11.5, 3), (11.5, 0))
    line(ax, (0, 0), (11.5, 0))
    ground(ax, (5, 0))
    node(ax, (0, 3), 1, dy=0.38); node(ax, (3.4, 3), 2, dy=0.38); node(ax, (7.2, 3), 3, dy=0.38)
    node(ax, (8.8, 3)); node(ax, (8.8, 0)); node(ax, (7.2, 0))
    text(ax, (-0.6, 1.5), "100 V peak\n50 Hz", ha="right", fontsize=9.5)
    text(ax, (1.7, 3.6), "R1 = 1 Ω", fontsize=10)
    text(ax, (5.3, 3.75), "L = 10 mH", fontsize=10)
    text(ax, (9.25, 1.5), "C\n10 μF", ha="left", fontsize=10)
    text(ax, (11.95, 1.5), "LOAD\n100 Ω", ha="left", fontsize=10)
    # fault (drawn dashed in chapter 5 only)
    save(fig, "network.svg")
    # the same with the fault
    fig, ax = canvas(6.4, 2.7, (-2.4, 13.2), (-1.3, 4.3))
    vsource(ax, (0, 0), (0, 3), kind="ac")
    resistor(ax, (0, 3), (3.4, 3))
    inductor(ax, (3.4, 3), (7.2, 3))
    line(ax, (7.2, 3), (11.5, 3))
    capacitor(ax, (8.8, 3), (8.8, 0))
    resistor(ax, (11.5, 3), (11.5, 0))
    line(ax, (0, 0), (11.5, 0))
    ground(ax, (5, 0))
    switch(ax, (7.2, 3), (7.2, 0), body=1.0)
    node(ax, (0, 3), 1, dy=0.38); node(ax, (3.4, 3), 2, dy=0.38); node(ax, (7.2, 3), 3, dy=0.38)
    text(ax, (6.95, 1.5), "FAULT", ha="right", fontsize=9.5, color="#B03030", fontweight="bold")
    text(ax, (-0.6, 1.5), "100 V peak\n50 Hz", ha="right", fontsize=9.5)
    text(ax, (1.7, 3.6), "R1 = 1 Ω", fontsize=10)
    text(ax, (5.3, 3.75), "L = 10 mH", fontsize=10)
    text(ax, (9.25, 1.5), "C\n10 μF", ha="left", fontsize=10)
    text(ax, (11.95, 1.5), "LOAD\n100 Ω", ha="left", fontsize=10)
    save(fig, "network_fault.svg")


def fig_rl_open():
    fig, ax = canvas(5.6, 2.9, (-1.9, 9.4), (-1.2, 4.4))
    vsource(ax, (0, 0), (0, 3))
    switch(ax, (0, 3), (3, 3), closed=True)
    resistor(ax, (3, 3), (6, 3))
    line(ax, (6, 3), (8, 3))
    inductor(ax, (8, 3), (8, 0))
    line(ax, (0, 0), (8, 0))
    ground(ax, (4, 0))
    text(ax, (-0.55, 1.5), "V\n10 V", ha="right", fontsize=10)
    text(ax, (1.5, 3.75), "switch opens\nat t = 3 ms", fontsize=9.5)
    text(ax, (4.5, 3.6), "R = 1 Ω", fontsize=10)
    text(ax, (8.5, 1.5), "L\n1 mH", ha="left", fontsize=10)
    save(fig, "rl_open_circuit.svg")


# ============================================================ HTML helpers (MathML)
import re

_TOK = re.compile(r"&#\d+;|'[A-Za-zΩμ]+|\d+(?:\.\d+)?|[A-Za-zΔτσπω]+|\S")


def X(s):
    """plain text -> MathML tokens; strings that already are MathML pass through"""
    if s.startswith("<"):
        return s
    out = []
    for tok in _TOK.findall(s):
        if tok.startswith("&#"):
            out.append("<mspace width='1em'/>")
        elif tok.startswith("'"):          # unit: upright, thin space before it
            out.append("<mspace width='0.2em'/><mi mathvariant='normal'>%s</mi>" % tok[1:])
        elif tok in "()":
            out.append("<mo stretchy='false'>%s</mo>" % tok)
        elif re.fullmatch(r"\d+(?:\.\d+)?", tok):
            out.append("<mn>%s</mn>" % tok)
        elif re.fullmatch(r"[A-Za-zΔτσπω]+", tok):
            if tok in ("Δt",):
                out.append("<mi mathvariant='normal'>Δ</mi><mi>t</mi>")
            elif len(tok) == 1 or tok == "Δ":
                out.append("<mi>%s</mi>" % tok)
            else:
                out.append("<mi mathvariant='normal'>%s</mi>" % tok)
        else:
            out.append("<mo>%s</mo>" % tok)
    return "".join(out)


def cat(*parts):
    return "<mrow>" + "".join(X(p) for p in parts) + "</mrow>"


def fr(a, b):
    return "<mfrac>%s%s</mfrac>" % (cat(a), cat(b))


def sb(a, b):
    return "<msub>%s%s</msub>" % (cat(a), cat(b))


def sp(a, b):
    return "<msup>%s%s</msup>" % (cat(a), cat(b))


def br(*parts, o="[", c="]"):
    return "<mrow><mo>%s</mo>%s<mo>%s</mo></mrow>" % (o, cat(*parts), c)


def integral(lo, hi, *body):
    return "<mrow><msubsup><mo>∫</mo>%s%s</msubsup>%s</mrow>" % (cat(lo), cat(hi), cat(*body))


def num(x, d=4):
    if isinstance(x, str):
        return "<mn class='num'>%s</mn>" % x
    s = ("%.*f" % (d, x)).replace("-", "−")
    if s in ("−0." + "0" * d,):
        s = s[1:]
    return "<mn class='num'>%s</mn>" % s


def mat(A, d=4):
    A = np.atleast_2d(A)
    rows = "".join("<mtr>" + "".join("<mtd>%s</mtd>" % num(x, d) for x in r) + "</mtr>" for r in A)
    return "<mrow><mo>[</mo><mtable columnspacing='1.1em'>%s</mtable><mo>]</mo></mrow>" % rows


def col(v, d=4):
    return mat(np.asarray(v).reshape(-1, 1), d)


def eq(*parts, label=None):
    s = "<math display='block'>%s</math>" % cat(*parts)
    if label:
        return "<div class='eq'>%s<span class='eqn'>(%s)</span></div>" % (s, label)
    return "<div class='eq'>%s</div>" % s


def m(*parts):
    """inline maths"""
    return "<math>%s</math>" % cat(*parts)


I_HIST = sb("I", "hist")
BG, BV, BI = ("<mi mathvariant='normal'>%s</mi>" % x for x in ("𝐆", "𝐯", "𝐢"))   # bold G, v, i
R_L = sb("R", "L")
R_C = sb("R", "C")


def f(x, d=4):
    return ("%.*f" % (d, x)).replace("-", "−")


# ============================================================ the book
def build():
    os.makedirs(FIG, exist_ok=True)
    print("figures ...")
    fig_cover(); fig_photo_movie(); fig_rl(); fig_trapezoid(); fig_companion(); fig_rl_companion()
    fig_network(); fig_rl_open()

    print("numbers ...")
    # ---------------- chapter 3: RL circuit
    dt = 1e-4
    rl = rl_circuit(dt).run(5e-3)
    check("rl.net", rl, ["R", "L"])
    exact = lambda t: 10 * (1 - np.exp(-t / 1e-3))
    rows = []
    for k, s in enumerate(rl[:10]):
        t = s["t"]
        rows.append((k + 1, t * 1e3, s["hist"]["L"], s["v"][2], s["i"]["L"], exact(t), exact(t - dt / 2)))
    s1, s2, s3 = rl[0], rl[1], rl[2]

    # plot: simulation vs exact
    fig, axs = plt.subplots(1, 2, figsize=(6.6, 2.6), gridspec_kw={"width_ratios": [1.5, 1]})
    tt = np.linspace(0, 5e-3, 500)
    ts = np.array([0] + [s["t"] for s in rl])
    isim = np.array([0] + [s["i"]["L"] for s in rl])
    for ax, xmax in ((axs[0], 5), (axs[1], 0.62)):
        ax.plot(tt * 1e3, exact(tt), color=GREY, lw=2.2, label="exact")
        ax.plot(ts * 1e3, isim, "o-", color=ACCENT, ms=3.2 if xmax < 1 else 2, lw=1.1, label="EMT, Δt = 0.1 ms")
        ax.set_xlim(0, xmax); ax.set_xlabel("time (ms)")
    axs[1].plot(tt * 1e3, exact(tt - dt / 2) * (tt >= dt / 2), "--", color=INK, lw=1, label="exact, Δt/2 later")
    axs[0].set_ylabel("current i (A)"); axs[0].set_ylim(0, 10.5); axs[1].set_ylim(0, 5.5)
    axs[0].legend(frameon=False, fontsize=9, loc="lower right"); axs[1].legend(frameon=False, fontsize=8.5, loc="upper left")
    axs[1].set_title("the first six steps", fontsize=10)
    fig.tight_layout(); save(fig, "rl_result.svg")

    # time-step study: error at 1 ms
    study = []
    for d in (5e-4, 1e-4, 2e-5):
        r = rl_circuit(d).run(1e-3)
        study.append((d * 1e3, r[-1]["i"]["L"], abs(r[-1]["i"]["L"] - exact(1e-3)), abs(r[-1]["i"]["L"] - exact(1e-3 - d / 2))))

    # ---------------- chapter 4: network
    dtn = 5e-5
    net = network(dtn).run(0.08)
    check("network.net", net, ["R1", "L", "C", "LOAD"])
    G = net[0]["G"]
    GUU = G[1:, 1:]
    GUK = G[1:, :1]
    n1, n2 = net[0], net[1]
    # steady-state check: phasor solution of the same circuit
    w = 2 * math.pi * 50
    ZL, ZC = 1j * w * 0.01, 1 / (1j * w * 10e-6)
    Zp = 1 / (1 / ZC + 1 / 100)
    V3 = 100 * Zp / (1 + ZL + Zp)
    fig, ax = plt.subplots(figsize=(6.6, 2.5))
    tn = np.array([s["t"] for s in net]) * 1e3
    ax.plot(tn, [s["v"][3] for s in net], color=ACCENT, lw=1.1, label="node 3, EMT")
    tt = np.linspace(0, 0.08, 2000)
    ax.plot(tt * 1e3, abs(V3) * np.cos(w * tt + np.angle(V3)), "--", color=INK, lw=0.9, label="steady state (phasor)")
    ax.set_xlabel("time (ms)"); ax.set_ylabel("voltage (V)"); ax.set_xlim(0, 80)
    ax.set_ylim(-125, 205)
    ax.legend(frameon=False, fontsize=9, loc="upper right", ncol=2)
    fig.tight_layout(); save(fig, "network_result.svg")
    # first-peak of the energisation transient
    v3 = np.array([s["v"][3] for s in net])
    peak = np.abs(v3).max()

    # ---------------- chapter 5: fault
    netf = network(dtn, fault=(0.03, 0.06)).run(0.08)
    check("network_fault.net", netf, ["R1", "L", "C", "LOAD", "FAULT"])
    Gf_on = network(dtn, fault=(0.03, 0.06)).G(0.035)[1:, 1:]
    Gf_off = network(dtn, fault=(0.03, 0.06)).G(0.01)[1:, 1:]
    fig, axs = plt.subplots(2, 1, figsize=(6.6, 3.9), sharex=True)
    tf = np.array([s["t"] for s in netf]) * 1e3
    for ax in axs:
        ax.axvspan(30, 60, color=FAULT, lw=0)
    axs[0].plot(tf, [s["v"][3] for s in netf], color=ACCENT, lw=1.0)
    axs[0].set_ylabel("node 3 (V)")
    iL = np.array([s["i"]["L"] for s in netf])
    axs[1].plot(tf, iL, color=INK, lw=1.0)
    axs[1].set_ylabel("current in L (A)"); axs[1].set_xlabel("time (ms)"); axs[1].set_xlim(0, 80)
    axs[0].text(45, axs[0].get_ylim()[1] * 0.82, "fault", ha="center", color="#B03030", fontsize=10)
    fig.tight_layout(); save(fig, "fault_result.svg")
    ifault_peak = np.abs(iL[(tf > 30) & (tf < 60)]).max()
    f0 = 1 / (2 * math.pi * math.sqrt(0.01 * 10e-6))

    # ---------------- chapter 7: opening the switch
    ro = rl_circuit(dt, opens=3e-3).run(5e-3)
    check("rl_open.net", ro, ["SWITCH", "R", "L"])
    fig, axs = plt.subplots(1, 2, figsize=(6.6, 2.5), gridspec_kw={"width_ratios": [1.4, 1]})
    to = np.array([0] + [s["t"] for s in ro]) * 1e3
    io = np.array([0] + [s["i"]["L"] for s in ro])
    vo = np.array([0] + [s["v"][3] for s in ro])
    axs[0].plot(to, io, "-", color=INK, lw=1.3)
    axs[0].axvline(3, color=GREY, ls="--", lw=0.8)
    axs[0].set_xlabel("time (ms)"); axs[0].set_ylabel("current in L (A)"); axs[0].set_xlim(0, 5)
    axs[0].text(3.1, 5, "switch\nopens", fontsize=8.5, color="#444")
    m_ = (to >= 2.55) & (to <= 3.85)
    axs[1].plot(to[m_], vo[m_], "o-", color=ACCENT, ms=3.5, lw=0.9)
    axs[1].set_ylabel("voltage across L (V)")
    axs[1].axvline(3, color=GREY, ls="--", lw=0.8)
    axs[1].set_xlabel("time (ms)"); axs[1].set_title("zoomed in: every step", fontsize=10)
    fig.tight_layout(); save(fig, "rl_open_result.svg")
    k_open = int(round(3e-3 / dt)) - 1     # index of the step at 3 ms
    i_before = ro[k_open - 1]["i"]["L"]
    i_after = max(abs(ro[k_open + j]["i"]["L"]) for j in range(1, 20))
    v_before = ro[k_open - 1]["v"][3]
    v_after = [ro[k_open + j]["v"][3] for j in range(5)]

    print("html ...")
    H = []
    a = H.append

    # ---------------------------------------------------------------- cover
    a("""
<section class="cover">
  <div class="titlebox">Tiny book of EMT simulation</div>
  <div class="subtitle">Closing a switch</div>
  <div class="tile-wrap"><div class="tile"><img src="fig/cover.svg" alt=""></div>
  <div class="tile reflection"><img src="fig/cover.svg" alt=""></div></div>
  <div class="author">By Amila Pathirana</div>
</section>
""")

    # ---------------------------------------------------------------- 1
    a("""
<h2>1. Introduction</h2>
<p>When you flick a light switch, close a circuit breaker, or lightning strikes a line, the voltages
and currents in the network do not jump straight to their new values. For a few milliseconds they
swing, overshoot and ring before they settle down. These short events are called
<b>electromagnetic transients</b>, and <b>EMT simulation</b> is the way we calculate them on a computer.</p>
<p>Most power-system tools, such as load flow and short-circuit programs, work with phasors. A phasor
describes a sine wave that has been running forever with a fixed amplitude and phase. That is perfect
for the steady state, but it cannot tell you what happens in the first few milliseconds after a switch
closes, because nothing is a steady sine wave yet.</p>
<p>The good news is that EMT simulation is built from things you already know: Ohm's law, Kirchhoff's
current law, and the two equations of the inductor and the capacitor. There is only one new trick, called
the <i>companion model</i>, and it is much simpler than it sounds.</p>
<p>Going through a simple example is the best way to understand EMT simulation. Here is one such example.</p>
""")

    # ---------------------------------------------------------------- 2
    a("""
<h2>2. A simple example: a photo and a movie</h2>
<p>Imagine you want to tell a friend how a child on a swing is moving. You could give them one photo of
the swing with a note on the back: <i>"it swings one metre each way, once every two seconds."</i> That is
a phasor: one picture, plus an amplitude and a frequency. It works perfectly, as long as the swing keeps
moving the same way.</p>
<p>Now someone gives the swing a hard push. Your photo cannot tell your friend what happens next. For
that you need a movie: one picture every fraction of a second, where each picture follows from the one
before it.</p>
<figure><img src="fig/photo_movie.svg" style="width:100%">
<figcaption>Figure 1: A phasor is one photo of a steady sine wave. An EMT simulation is a movie: the
network is calculated again every time step Δt, and each frame follows from the frame before it.</figcaption></figure>
<p>EMT simulation is the movie. We calculate the network at one small time step Δt after another, and
each step is calculated from the step before it. A small Δt gives a smooth movie but needs more frames,
which means more work. Typical time steps are 20 to 100 μs for switching studies, a few μs for
power electronics, and well below a microsecond for lightning.</p>
""")

    # ---------------------------------------------------------------- 3
    hist3 = s3["hist"]["L"]
    a(f"""
<h2>3. An EMT simulation of a simple circuit</h2>
<p>Figure 2 shows the circuit we will simulate: a 10 V battery, a switch, a 1 Ω resistor and a 1 mH
inductor. Everything is at rest, and the switch closes at <i>t</i> = 0. What is the current
<i>i</i>(<i>t</i>)?</p>
<figure><img src="fig/rl_circuit.svg" style="width:68%">
<figcaption>Figure 2: The circuit of this chapter. Node 1 is the battery's terminal, node 2 is the
top of the inductor.</figcaption></figure>
<p>This circuit is simple enough to solve with pen and paper, and that is exactly why we use it: the exact
answer lets us check our simulation.</p>
{eq("i(t) =", fr("V", "R"), br("1 −", sp("e", "− t / τ"), o="(", c=")"), ",&#8195;", "τ =", fr("L", "R"), "= 1 'ms")}
<p>The current rises towards <i>V</i>/<i>R</i> = 10 A, and reaches 63 % of it after one time constant
τ = 1 ms. Our goal is to get the same answer without solving any differential equation: only
arithmetic with resistors.</p>

<h3>a. Chop time into small steps</h3>
<p>We choose a time step Δt = 0.1 ms and calculate the circuit only at <i>t</i> = Δt, 2Δt, 3Δt and so
on. The resistor is easy: at every instant its current is its voltage divided by <i>R</i>. The inductor
is the troublemaker:</p>
{eq("v = L", fr("di", "dt"))}
<p>This equation links the current now to how the current was changing a moment ago. To handle it we
need the companion model.</p>

<h3>b. The companion model</h3>
<p>"Companion model" sounds complex, but it is not.</p>
<p>Rearrange the inductor equation and add up (integrate) the voltage over one time step:</p>
{eq("i(t) = i(t − Δt) +", fr("1", "L"), integral("t − Δt", "t", "v dt"), label=1)}
<p>We do not know exactly how <i>v</i> changes inside the step, so we approximate the integral by the
area of a trapezoid, as in Figure 3. This is called the <b>trapezoidal rule</b>.</p>
<figure><img src="fig/trapezoid.svg" style="width:52%">
<figcaption>Figure 3: The trapezoidal rule. The area under the curve (the integral of <i>v</i>) is
replaced by the area of the orange trapezoid. The small grey sliver is the error.</figcaption></figure>
{eq(integral("t − Δt", "t", "v dt"), "≈", fr("Δt", "2"), br("v(t) + v(t − Δt)"), label=2)}
<p>Put (2) into (1) and sort the terms into the ones that belong to <i>now</i> and the ones that belong
to the <i>last step</i>:</p>
{eq("i(t) =", fr("Δt", "2L"), "v(t) +", br("i(t − Δt) +", fr("Δt", "2L"), "v(t − Δt)"), label=3)}
<p>Look at the two parts of (3). The first part is a conductance Δt/2L multiplied by the voltage now.
That is exactly how a resistor behaves, with resistance</p>
{eq(R_L, "=", fr("2L", "Δt"))}
<p>The second part, in the brackets, only contains values from the last step, which we already know. We
call it the <b>history current</b>. A current that is already known is simply a current source. So we
can write (3) as</p>
{eq("i(t) =", fr("v(t)", R_L), "+", I_HIST, "(t),&#8195;&#8195;", I_HIST, "(t) = i(t − Δt) +", fr("v(t − Δt)", R_L), label=4)}
<p>That is the whole trick. <b>For one time step, an inductor is a resistor in parallel with a current
source.</b> The resistor never changes (as long as Δt does not change); only the current source is
updated at every step. The capacitor gets the same treatment from <i>i</i> = <i>C</i>&#8202;d<i>v</i>/d<i>t</i>,
with <i>R<sub>C</sub></i> = Δt/2C and a history current with the opposite sign (Figure 4).</p>
<figure><img src="fig/companion.svg" style="width:86%">
<figcaption>Figure 4: Companion models. For one time step, an inductor or a capacitor between nodes
<i>k</i> and <i>m</i> becomes a resistor and a current source.</figcaption></figure>
<p>For our inductor, {m(R_L, "=", fr("2 × 0.001", "0.0001"), "= 20 'Ω")}.</p>

<h3>c. Solving one time step</h3>
<p>Replace the inductor in Figure 2 with its companion model. Now the circuit contains only a battery,
resistors and a current source (Figure 5), and we can solve it with nothing but Ohm's law.</p>
<figure><img src="fig/rl_companion.svg" style="width:70%">
<figcaption>Figure 5: The circuit of Figure 2 for one time step, with the inductor replaced by its
companion model.</figcaption></figure>
<p>The voltage of node 1 is known: it is the battery voltage <i>V</i>. The voltage of node 2,
<i>v</i><sub>2</sub>, is unknown. Kirchhoff's current law at node 2 says that the current arriving
through <i>R</i> leaves through the companion model:</p>
{eq(fr(cat("V −", sb("v", "2")), "R"), "=", fr(sb("v", "2"), R_L), "+", I_HIST, "&#8195;⟹&#8195;",
    sb("v", "2"), "=", fr(cat(fr("V", "R"), "−", I_HIST), cat(fr("1", "R"), "+", fr("1", R_L))), label=5)}
<p>Once we have <i>v</i><sub>2</sub>, the inductor current follows from (4).</p>

<h3>d. Step by step, with numbers</h3>
<p>Before <i>t</i> = 0 everything is at rest: <i>i</i> = 0 and <i>v</i><sub>2</sub> = 0. Now let us
go through the first steps. Here, I tried not to skip any steps, so you can follow every one of them.</p>
<p class="step">Step 1, <i>t</i> = 0.1 ms</p>
<p>The history current comes from the last step, when everything was at rest:</p>
{eq(I_HIST, "= 0 +", fr("0", "20"), "=", num(0, 4), "'A")}
{eq(sb("v", "2"), "=", fr("10 / 1 − 0", "1 / 1 + 1 / 20"), "=", fr("10", "1.05"), "=", num(s1['v'][2]), "'V")}
{eq("i =", fr(num(s1['v'][2]), "20"), "+ 0 =", num(s1['i']['L']), "'A")}
<p class="step">Step 2, <i>t</i> = 0.2 ms</p>
<p>Now the history current uses the results of step 1:</p>
{eq(I_HIST, "=", num(s1['i']['L']), "+", fr(num(s1['v'][2]), "20"), "=", num(s2['hist']['L']), "'A")}
{eq(sb("v", "2"), "=", fr(cat("10 −", num(s2['hist']['L'])), "1.05"), "=", num(s2['v'][2]), "'V")}
{eq("i =", fr(num(s2['v'][2]), "20"), "+", num(s2['hist']['L']), "=", num(s2['i']['L']), "'A")}
<p class="step">Step 3, <i>t</i> = 0.3 ms</p>
{eq(I_HIST, "=", num(s2['i']['L']), "+", fr(num(s2['v'][2]), "20"), "=", num(hist3), "'A")}
{eq(sb("v", "2"), "=", fr(cat("10 −", num(hist3)), "1.05"), "=", num(s3['v'][2]), "'V")}
{eq("i =", fr(num(s3['v'][2]), "20"), "+", num(hist3), "=", num(s3['i']['L']), "'A")}
<p>Every step is the same three lines: <b>history current, node voltage, branch current</b>. A computer
does exactly this, only many thousands of times. Try calculating steps 4 and 5 yourself; Table 1 has
the answers.</p>
<table>
<caption>Table 1: The first ten steps, and the exact current from the formula at the start of this chapter.</caption>
<tr><th>step</th><th><i>t</i> (ms)</th><th><i>I</i><sub>hist</sub> (A)</th><th><i>v</i><sub>2</sub> (V)</th>
<th><i>i</i> (A)</th><th>exact <i>i</i> (A)</th></tr>
""" + "".join("<tr><td>%d</td><td>%.1f</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td>%s</td></tr>"
              % (r[0], r[1], f(r[2]), f(r[3]), f(r[4]), f(r[5])) for r in rows) + f"""
</table>

<h3>e. How good is the answer?</h3>
<p>Figure 6 puts the simulated current next to the exact one. After a few steps the simulation follows
the exact curve closely, but always slightly behind it. Why?</p>
<figure><img src="fig/rl_result.svg" style="width:100%">
<figcaption>Figure 6: Simulated (orange dots) and exact (grey) current. On the right, the first six
steps: the simulation follows the exact curve delayed by half a time step (black dashes).</figcaption></figure>
<p>Look at step 1 again. The trapezoidal rule assumed that the inductor voltage rose in a straight line
from 0 V (at <i>t</i> = 0, when everything was at rest) to {f(s1['v'][2], 2)} V. In reality it jumped to
10 V the moment the switch closed. A voltage that rises in a straight line over one step is, on average,
the same as a voltage that jumps in the middle of the step. So the simulation behaves as if the switch
had closed half a step late, at Δt/2. Shift the exact curve by Δt/2 and the two agree very well
(right of Figure 6). Making Δt smaller makes the delay smaller:</p>
<table>
<caption>Table 2: The current at <i>t</i> = 1 ms for three time steps (exact: {f(exact(1e-3))} A).</caption>
<tr><th>Δt (ms)</th><th>simulated <i>i</i> (A)</th><th>error (A)</th><th>error against the curve delayed by Δt/2 (A)</th></tr>
""" + "".join("<tr><td>%g</td><td class='num'>%s</td><td>%s</td><td>%s</td></tr>"
              % (r[0], f(r[1]), f(r[2], 5), f(r[3], 5)) for r in study) + """
</table>
<p>The lesson: <b>Δt must be small compared with the fastest thing you want to see</b>. Here the time
constant is 1 ms, and a step of 0.1 ms is plenty.</p>
""")

    # ---------------------------------------------------------------- 4
    gl, gc = dtn / (2 * 0.01), 2 * 10e-6 / dtn
    a(f"""
<h2>4. A bigger network</h2>
<p>Real networks have many nodes, and writing Kirchhoff's law by hand for each of them gets old quickly.
The computer does it with a matrix. Figure 7 shows a slightly bigger circuit: a 100 V, 50 Hz source
feeding a line (<i>R</i>1 and <i>L</i>), a cable that adds capacitance <i>C</i>, and a 100 Ω load.
The time step is Δt = 50 μs.</p>
<figure><img src="fig/network.svg" style="width:80%">
<figcaption>Figure 7: The network of chapters 4 and 5. Nodes 1, 2 and 3; node 0 is ground.</figcaption></figure>

<h3>a. Building the conductance matrix</h3>
<p>First, every element becomes a conductance (one over its resistance in the companion model):</p>
<table class="narrow">
<tr><th>element</th><th>between nodes</th><th>conductance</th></tr>
<tr><td><i>R</i>1 = 1 Ω</td><td>1 and 2</td><td class='num'>1/1 = 1 S</td></tr>
<tr><td><i>L</i> = 10 mH</td><td>2 and 3</td><td class='num'>Δt/2L = {gl:g} S</td></tr>
<tr><td><i>C</i> = 10 μF</td><td>3 and ground</td><td class='num'>2C/Δt = {gc:g} S</td></tr>
<tr><td>LOAD = 100 Ω</td><td>3 and ground</td><td class='num'>1/100 = 0.01 S</td></tr>
</table>
<p>Then each one is "stamped" into the matrix <b>G</b> with one simple rule: a conductance <i>g</i>
between nodes <i>k</i> and <i>m</i> adds <i>g</i> to <b>G</b><sub><i>kk</i></sub> and
<b>G</b><sub><i>mm</i></sub>, and subtracts <i>g</i> from <b>G</b><sub><i>km</i></sub> and
<b>G</b><sub><i>mk</i></sub>. If one end is ground, only the diagonal entry is touched. After all four
stamps:</p>
{eq(BG, "=", mat(G, 4))}
<p>Kirchhoff's current law for every node at once is then</p>
{eq(BG, BV, "=", BI, label=6)}
<p>where <b>v</b> holds the node voltages and <b>i</b> holds the currents injected into each node by
the history current sources. A history current <i>I</i><sub>hist</sub> flowing from node <i>k</i> to
node <i>m</i> takes <i>I</i><sub>hist</sub> out of <b>i</b><sub><i>k</i></sub> and puts it into
<b>i</b><sub><i>m</i></sub>.</p>

<h3>b. Known and unknown nodes</h3>
<p>The source fixes the voltage of node 1, so node 1 is <b>known</b>. Nodes 2 and 3 are
<b>unknown</b>. Split <b>G</b> into the rows and columns of the unknown (U) and known (K) nodes:</p>
{eq(sb(BG, "UU"), "=", mat(GUU, 4), ",&#8195;&#8195;", sb(BG, "UK"), "=", mat(GUK, 0))}
<p>and solve only for the unknown voltages:</p>
{eq(sb(BG, "UU"), sb(BV, "U"), "=", sb(BI, "U"), "−", sb(BG, "UK"), sb(BV, "K"), label=7)}
<p>Here is the beautiful part: <b>G</b> does not change from one step to the next. Only the right-hand
side does. So the computer factorises <b>G</b><sub>UU</sub> once (EMTSim uses an LU or LDL<sup>T</sup>
factorisation) and then every step is just a quick substitution. That is why an EMT program can run
millions of steps.</p>

<h3>c. One step, with numbers</h3>
<p class="step">Step 1, <i>t</i> = 50 μs</p>
<p>The source voltage is {m("100 cos(2π × 50 × 0.00005) =", num(n1['vK'][0]), "'V")}. Everything was at
rest before, so all history currents are zero and <b>i</b><sub>U</sub> = 0.</p>
{eq(sb(BI, "U"), "−", sb(BG, "UK"), sb(BV, "K"), "=", col([0, 0], 0), "−", mat(GUK, 0),
    mat([[n1['vK'][0]]], 4), "=", col(n1['rhs'], 4))}
{eq(sb(BV, "U"), "=", sp(sb(BG, "UU"), "−1"), col(n1['rhs'], 4), "=", col(n1['v'][2:], 4))}
<p>So after the first step, node 2 is at {f(n1['v'][2], 2)} V and node 3 is still almost at 0 V. The
current through the inductor is {m("0.0025 × (", num(n1['v'][2]), "−", num(n1['v'][3]), ") =",
                                      num(n1['i']['L'], 6), "'A")}, and the capacitor current is
{m(num(0.4, 1), "×", num(n1['v'][3]), "=", num(n1['i']['C'], 6), "'A")}.</p>
<p class="step">Step 2, <i>t</i> = 100 μs</p>
<p>The history currents, from (4) and Figure 4:</p>
{eq(sb("I", "hist,L"), "=", num(n1['i']['L'], 6), "+", num(gl, 4), "×", num(n1['v'][2] - n1['v'][3]), "=", num(n2['hist']['L'], 6), "'A")}
{eq(sb("I", "hist,C"), "= −", num(n1['i']['C'], 6), "−", num(gc, 1), "×", num(n1['v'][3]), "=", num(n2['hist']['C'], 6), "'A")}
<p><i>I</i><sub>hist,L</sub> flows from node 2 to node 3, and <i>I</i><sub>hist,C</sub> from node 3 to
ground, so</p>
{eq(sb(BI, "U"), "=", col([n2['inj'][1], n2['inj'][2]], 6), ",&#8195;", sb(BV, "K"), "=", num(n2['vK'][0]),
    "'V,&#8195;", sb(BV, "U"), "=", col(n2['v'][2:], 4))}
<p>And so on, step after step. Figure 8 shows the voltage of node 3 for the first 80 ms. When the source
is switched on, the inductor and the capacitor exchange energy at their natural frequency
{m("1 / (2π", "<msqrt>" + cat("LC") + "</msqrt>", ") ≈", num(f0, 0), "'Hz")}; the voltage overshoots to
{f(peak, 1)} V before the load damps the ringing and the steady state, which a phasor calculation
would give, takes over.</p>
<figure><img src="fig/network_result.svg" style="width:100%">
<figcaption>Figure 8: Voltage of node 3 after the source is switched on, and the steady state from a
phasor calculation of the same circuit.</figcaption></figure>

<h3>d. The time loop</h3>
<p>Put together, an EMT program is a loop over these steps. This is exactly the order EMTSim uses:</p>
<div class="loop">
<div><b>Once:</b> build <b>G</b> from the companion models and factorise <b>G</b><sub>UU</sub>.</div>
<div><b>Every step</b> (<i>t</i> = <i>t</i> + Δt):</div>
<ol>
<li>If a switch or fault changes state, rebuild <b>G</b> and factorise it again.</li>
<li>Update the known voltages <b>v</b><sub>K</sub> (the sources).</li>
<li>Calculate the history current of every inductor and capacitor, and add them up into <b>i</b>.</li>
<li>Solve <b>G</b><sub>UU</sub> <b>v</b><sub>U</sub> = <b>i</b><sub>U</sub> − <b>G</b><sub>UK</sub> <b>v</b><sub>K</sub>.</li>
<li>Calculate the current in every element, and save the results.</li>
</ol>
</div>
""")

    # ---------------------------------------------------------------- 5
    a(f"""
<h2>5. Switches and faults</h2>
<p>A switch is simply a resistor that changes its value: a very small resistance when it is closed
(EMTSim uses 0.01 Ω) and a very large one when it is open (1 MΩ). A fault is a switch from a node to
ground. When it changes state, its conductance changes, so <b>G</b> changes. That is step 1 of the
time loop: rebuild <b>G</b>, factorise it again, and carry on. The history currents are not touched,
so the inductors and capacitors remember their current and voltage across the switching instant, just as
they do in real life.</p>
<p>Let us put a fault on node 3 of our network at 30 ms and clear it at 60 ms (Figure 9).</p>
<figure><img src="fig/network_fault.svg" style="width:80%">
<figcaption>Figure 9: The network of Figure 7 with a fault from node 3 to ground.</figcaption></figure>
<p>While the fault is open, it adds 1/10<sup>6</sup> S to <b>G</b><sub>33</sub>. When it closes, it
adds 1/0.01 = 100 S:</p>
{eq("before:&#8195;", sb(BG, "UU"), "=", mat(Gf_off, 6), "&#8195;&#8195;during:&#8195;", sb(BG, "UU"), "=", mat(Gf_on, 4))}
<p>Figure 10 shows the result. When the fault is applied, node 3 collapses to almost zero and the
capacitor discharges into the fault. The current in <i>L</i> grows to about {f(ifault_peak, 1)} A,
limited mostly by the inductor. When the fault is cleared, the capacitor and the inductor ring again at
about {f0:.0f} Hz before the network settles back to its steady state.</p>
<figure><img src="fig/fault_result.svg" style="width:100%">
<figcaption>Figure 10: Voltage of node 3 and current in the inductor, with the fault (shaded) from 30 to
60 ms.</figcaption></figure>
""")

    # ---------------------------------------------------------------- 6
    def netfile(name):
        with open(os.path.join(NETS, name), encoding="utf-8") as fh:
            return fh.read().strip().replace("&", "&amp;").replace("<", "&lt;")
    a(f"""
<h2>6. Try it yourself with EMTSim</h2>
<p>Everything in this book was calculated with the same steps that EMTSim uses, and checked against
it: EMTSim gives the same numbers, to the last digit. You can run every example yourself. An EMTSim
netlist has one line per element: the type, the nodes it connects (0 is ground) and its value.
This is the circuit of chapter 3:</p>
<pre>{netfile("rl.net")}</pre>
<p>and this is the network with the fault, from chapter 5:</p>
<pre>{netfile("network_fault.net")}</pre>
<p>Run them from the EMTSim folder with either solver:</p>
<pre>build\\emtsim.exe docs\\book\\circuits\\rl.net
python main.py docs\\book\\circuits\\network_fault.net
python plot.py</pre>
<p>The node voltages are written to <code>results.csv</code> and the element currents to
<code>currents.csv</code>. Compare the first lines of <code>results.csv</code> with Table 1. You can
also open the circuit editor with <code>gui.bat</code>, draw the circuit, press Run, and drag across a
plot to zoom into the first few steps.</p>
<p>Then try changing things. Make Δt ten times bigger and see the error grow. Move the fault to node 2.
Change the load to 10 Ω and watch the ringing die out faster.</p>
""")

    # ---------------------------------------------------------------- 7
    a(f"""
<h2>7. What if we open the switch?</h2>
<p>So far, we have only closed switches. Let us take the circuit of chapter 3 again, wait until the
current has almost reached 10 A, and open the switch at <i>t</i> = 3 ms (Figure 11).</p>
<figure><img src="fig/rl_open_circuit.svg" style="width:62%">
<figcaption>Figure 11: The circuit of chapter 3, with a switch that opens at 3 ms.</figcaption></figure>
<p>In a real circuit, the current in an inductor cannot stop instantly. When the switch opens, the
inductor drives the voltage across the opening contacts up very high (that is why breakers draw arcs),
and the current falls to zero very quickly. Now look at what our simulation says (Figure 12).</p>
<figure><img src="fig/rl_open_result.svg" style="width:100%">
<figcaption>Figure 12: Left: current in the inductor. Right: voltage across the inductor at every
step around the opening. Both calculated with the trapezoidal rule and Δt = 0.1 ms.</figcaption></figure>
<p>The current looks fine: just before the switch opens it is {f(i_before, 2)} A, and from the next
step on it is practically zero (less than {i_after:.4f} A). But look at the voltage across the
inductor. Just before the opening it is {f(v_before, 2)} V. In the steps after it, the simulation gives
{", ".join(f(x, 1) for x in v_after)} V, and so on, flipping sign at every single step for as long as
we care to simulate. No current flows, and yet the inductor voltage keeps jumping between plus and
minus {f(abs(v_after[-1]), 0)} V.</p>
<p>Does the voltage in the real circuit do that? Or is it our simulation? Try equation (4) with the
1 MΩ of the open switch in series with <i>R<sub>L</sub></i> = 20 Ω, and see what happens to
<i>I</i><sub>hist</sub> from one step to the next.</p>
""")

    css = CSS
    html = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Tiny book of EMT simulation</title>"
            "<style>%s</style></head><body>%s</body></html>" % (css, "\n".join(H)))
    out = os.path.join(HERE, "emt_book.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("  wrote", os.path.relpath(out, ROOT))
    return out


CSS = r"""
@page { size: letter; margin: 0.95in 1.05in 0.9in 1.05in;
  @bottom-left { content: counter(page) "  |  Page"; font: 10pt Calibri, 'Segoe UI', sans-serif; color: #7f7f7f;
                 border-top: 0.6pt solid #d0d0d0; vertical-align: top; padding-top: 4pt; width: 100%; } }
@page :first { @bottom-left { content: none; border: none; } }
html { background: white; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 12.5pt; line-height: 1.32; color: #111;
       margin: 0; background: white; }
math { font-family: 'Cambria Math', 'STIX Two Math', serif; font-size: 1.05em; }
.num, mn.num { color: #C55A11; }
p { margin: 0 0 0.75em; text-align: justify; text-indent: 1.6em; hyphens: auto; }
h2 { background: #000; color: #fff; font-size: 15.5pt; font-weight: bold; padding: 2pt 10pt 1pt;
     margin: 1.3em 0 0.6em; break-after: avoid; }
h3 { background: #000; color: #fff; font-size: 14pt; font-weight: bold; padding: 1pt 10pt 0;
     margin: 1.2em 0 0.55em 0.9in; break-after: avoid; }
h2 + p, h3 + p { break-before: avoid; }
p.step { text-indent: 0; font-weight: bold; display: inline-block; background: #d9d9d9; padding: 0 5pt;
         margin: 0.6em 0 0.4em 0.9in; }
.eq { position: relative; margin: 0.5em 0 0.7em; break-inside: avoid; text-align: center; }
.eqn { position: absolute; right: 0; top: 50%; transform: translateY(-50%); }
figure { margin: 0.9em 0 1em; text-align: center; break-inside: avoid; }
figure img { display: block; margin: 0 auto; }
figcaption { text-align: left; font-size: 11.5pt; margin-top: 0.35em; }
table { border-collapse: collapse; margin: 0.6em auto 1em; font-size: 11pt; break-inside: avoid; }
table.narrow { margin-left: auto; margin-right: auto; }
caption { caption-side: top; text-align: left; font-size: 11.5pt; padding-bottom: 0.4em; }
th, td { border-bottom: 0.6pt solid #bbb; padding: 2pt 9pt; text-align: right; }
th { border-bottom: 1.2pt solid #000; font-weight: bold; }
td:first-child, th:first-child { text-align: left; }
pre { font-family: Consolas, 'Courier New', monospace; font-size: 9.6pt; background: #f2f2f2;
      border-left: 3pt solid #000; padding: 6pt 10pt; white-space: pre-wrap; break-inside: avoid; line-height: 1.25; }
code { font-family: Consolas, monospace; font-size: 0.9em; }
.loop { border: 1pt solid #000; padding: 8pt 14pt 4pt; margin: 0.6em 0 1em; break-inside: avoid; }
.loop div { margin-bottom: 4pt; }
.loop ol { margin: 2pt 0 6pt; padding-left: 1.6em; }
.loop li { margin-bottom: 2pt; }
/* cover */
.cover { height: 9.1in; display: flex; flex-direction: column; align-items: center; break-after: page; }
.titlebox { background: #000; color: #fff; font-family: 'Segoe Script', 'Segoe Print', cursive; font-size: 40pt;
            line-height: 1.25; text-align: center; padding: 18pt 28pt 22pt; width: 82%; margin-top: 0.1in; }
.subtitle { font-family: 'Segoe Script', 'Segoe Print', cursive; color: #7f7f7f; font-size: 30pt; margin: 0.35in 0 0.25in; }
.tile-wrap { display: flex; flex-direction: column; align-items: center; }
.tile { width: 1.65in; height: 3.75in; border-radius: 10pt; background: white; border: 1pt solid #cfcfcf;
        box-shadow: inset 0 0 14pt rgba(0,0,0,0.25), 0 1pt 3pt rgba(0,0,0,0.2); overflow: hidden;
        display: flex; align-items: center; justify-content: center; }
.tile img { width: 88%; height: 92%; object-fit: contain; }
.tile.reflection { height: 0.9in; transform: scaleY(-1); opacity: 0.35; margin-top: 3pt; border: none; box-shadow: none;
                   -webkit-mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.9) 100%);
                   mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.9) 100%);
                   align-items: flex-end; }
.tile.reflection img { height: 3.45in; width: 88%; object-fit: contain; object-position: bottom; }
.author { margin-top: auto; background: #000; color: #fff; font-family: 'Segoe Script', 'Segoe Print', cursive;
          font-size: 21pt; width: 100%; text-align: center; padding: 3pt 0 5pt; }
@media screen { body { max-width: 6.4in; margin: 0.6in auto; } .cover { height: auto; min-height: 9.1in; } }
"""


def print_pdf(html):
    candidates = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  shutil.which("msedge") or "", shutil.which("google-chrome") or "", shutil.which("chromium") or ""]
    browser = next((c for c in candidates if c and os.path.exists(c)), None)
    if not browser:
        print("  no Edge or Chrome found: open emt_book.html and print it to PDF")
        return
    pdf = os.path.join(HERE, "TinyBookOfEMT.pdf")
    prof = tempfile.mkdtemp()
    try:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--user-data-dir=" + prof, "--virtual-time-budget=5000",
                        "--print-to-pdf=" + pdf, "file:///" + html.replace("\\", "/")],
                       check=True, capture_output=True, timeout=120)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    print("  wrote", os.path.relpath(pdf, ROOT))


if __name__ == "__main__":
    out = build()
    if "--no-pdf" not in sys.argv:
        print("pdf ...")
        print_pdf(out)
