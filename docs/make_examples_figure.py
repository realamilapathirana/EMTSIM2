"""Generate docs/examples_new_elements.png from the C++ results of four example studies.

Run from the repository root after building the C++ version:  python docs/make_examples_figure.py
"""
import os
import subprocess

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = next(p for p in (os.path.join(ROOT, "build", "emtsim.exe"), os.path.join(ROOT, "build", "Release", "emtsim.exe"),
                       os.path.join(ROOT, "build", "emtsim")) if os.path.isfile(p))


def run(name):
    subprocess.run([EXE, os.path.join(ROOT, "circuits", name + ".net")], cwd=ROOT, capture_output=True, check=True)
    v = np.genfromtxt(os.path.join(ROOT, "results.csv"), delimiter=",", names=True)
    c = np.genfromtxt(os.path.join(ROOT, "currents.csv"), delimiter=",", names=True, deletechars="")
    return v, c


TEAL, ORANGE, GREY, RED, BLUE = "#21A99B", "#E8833A", "#6B7280", "#D64545", "#2F6FD6"
fig, ax = plt.subplots(2, 2, figsize=(13, 7.5))

v, c = run("line_energisation")
t = v["time"]*1000
ax[0, 0].plot(t, v["V7"]/187794, color=GREY, lw=1, label="no arresters")
ax[0, 0].plot(t, v["V13"]/187794, color=TEAL, lw=1.3, label="with surge arresters")
ax[0, 0].set_xlim(19, 32)
ax[0, 0].set_title("Line energisation (Bergeron line, 100 km): open-end voltage, phase a")
ax[0, 0].set_ylabel("pu"); ax[0, 0].set_xlabel("ms"); ax[0, 0].legend(loc="lower left", fontsize=9)

v, c = run("transformer_inrush")
t = v["time"]*1000
ax[0, 1].plot(t, c["T_SAT.m"], color=RED, lw=1, label="saturating core")
ax[0, 1].plot(t, c["T_LIN.m"]*50, color=GREY, lw=1, label="linear core (x50)")
ax[0, 1].set_title("Transformer inrush: magnetising current after energising at a voltage zero")
ax[0, 1].set_ylabel("A"); ax[0, 1].set_xlabel("ms"); ax[0, 1].legend(loc="upper right", fontsize=9)

v, c = run("rectifier")
t = v["time"]*1000
ax[1, 0].plot(t, v["V4"] - v["V5"], color=TEAL, lw=1, label="thyristor bridge, alpha = 30 deg")
ax[1, 0].plot(t, v["V6"] - v["V7"], color=ORANGE, lw=1, label="diode bridge with capacitor")
ax[1, 0].axhline(1.35*400*np.cos(np.radians(30)), color=GREY, ls="--", lw=0.8)
ax[1, 0].set_title("Six-pulse rectifiers on a 400 V supply: DC voltage")
ax[1, 0].set_ylabel("V"); ax[1, 0].set_xlabel("ms"); ax[1, 0].legend(loc="lower right", fontsize=9)

v, c = run("machines")
t = v["time"]
a1 = ax[1, 1]
a1.plot(t, c["MOTOR.speed[pu]"], color=BLUE, lw=1.3, label="motor speed (pu)")
a1.plot(t, c["GEN.speed[pu]"], color=TEAL, lw=1.3, label="generator speed (pu)")
a1.axvspan(1.0, 1.15, color=RED, alpha=0.1, lw=0)
a1.set_ylim(0, 1.1); a1.set_xlabel("s"); a1.set_ylabel("pu")
a2 = a1.twinx()
a2.plot(t, c["GEN.delta[deg]"], color=ORANGE, lw=1, label="generator rotor angle (deg)")
a2.set_ylabel("deg")
a1.set_title("Motor start, then a 150 ms three-phase fault at the generator")
h1, l1 = a1.get_legend_handles_labels(); h2, l2 = a2.get_legend_handles_labels()
a1.legend(h1 + h2, l1 + l2, loc="lower right", fontsize=9)

for a in ax.ravel():
    a.grid(True, alpha=0.3)
fig.tight_layout()
out = os.path.join(ROOT, "docs", "examples_new_elements.png")
fig.savefig(out, dpi=100)
print("Saved", os.path.relpath(out, ROOT))
