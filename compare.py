"""Run the Python and C++ simulators and compare their results and speed.

Usage (build the C++ version first with build.bat or cmake):
    python compare.py                                 # built-in circuits: dataloader.py vs src/circuit.cpp
    python compare.py --netlist circuits/grid100.net  # the same netlist file in both versions
    python compare.py --netlist circuits/grid100.net --plot --save compare.png

With --netlist both versions read the same file, so they are guaranteed to
simulate the same circuit. Without it, each version uses its own built-in
circuit, so keep dataloader.py and src/circuit.cpp in sync.

Timing is the best of --repeat runs and covers building the network and the
time loop (and reading the netlist), not process start, plotting or writing
results.
"""
import argparse
import contextlib
import importlib
import io
import os
import subprocess
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def run_python(netlist, repeat):
    import dataloader
    import emtcls
    import main
    nets = []
    emtcls.Network.plotv = lambda self: nets.append(self)   # capture instead of plotting
    best = float("inf")
    for _ in range(repeat):
        if not netlist:
            importlib.reload(dataloader)                     # fresh element objects for every run
        with contextlib.redirect_stdout(io.StringIO()):
            t0 = time.perf_counter()
            main.run(netlist)
            best = min(best, time.perf_counter() - t0)
    net = nets[-1]
    return np.array(net.time), np.array(net.trace), best, net.current_names, np.array(net.ctrace)


def find_cpp_exe():
    for rel in ("build/emtsim.exe", "build/Release/emtsim.exe", "build/emtsim", "build/Release/emtsim"):
        path = os.path.join(HERE, rel)
        if os.path.isfile(path):
            return path
    raise SystemExit("C++ simulator not found in build/. Build it first with build.bat or cmake.")


def run_cpp(netlist, repeat):
    exe = find_cpp_exe()
    cmd = [exe] + ([os.path.abspath(netlist)] if netlist else [])
    best = float("inf")
    for _ in range(repeat):
        out = subprocess.run(cmd, cwd=HERE, check=True, capture_output=True, text=True).stdout
        # The C++ program times its own setup + time loop
        ms = [float(l.split(":")[1].split()[0]) for l in out.splitlines() if l.startswith("Simulation time:")]
        if not ms:
            raise SystemExit("C++ simulator did not report its time: rebuild it (build.bat).")
        best = min(best, ms[0]/1000.0)
    data = np.loadtxt(os.path.join(HERE, "results.csv"), delimiter=",", skiprows=1, ndmin=2)
    with open(os.path.join(HERE, "currents.csv")) as f:
        cnames = f.readline().strip().split(",")[1:]
    cur = np.loadtxt(os.path.join(HERE, "currents.csv"), delimiter=",", skiprows=1, ndmin=2)[:, 1:]
    return data[:, 0], data[:, 1:], best, exe, cnames, cur


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--netlist", help="netlist file to run in both versions")
    ap.add_argument("--repeat", type=int, default=3, help="runs per version; the fastest is reported (default 3)")
    ap.add_argument("--plot", action="store_true", help="plot both versions and their difference")
    ap.add_argument("--save", help="save the plot to this file instead of showing it")
    args = ap.parse_args()

    circuit = args.netlist or "built-in (dataloader.py / src/circuit.cpp)"
    t_py, V_py, s_py, cn_py, I_py = run_python(args.netlist, args.repeat)
    t_cpp, V_cpp, s_cpp, exe, cn_cpp, I_cpp = run_cpp(args.netlist, args.repeat)
    steps, n = V_py.shape

    print("Circuit: %s" % circuit)
    print("%d nodes, %d time steps\n" % (n, steps))
    print("Speed (best of %d runs, network setup + time loop)" % args.repeat)
    print("  Python : %10.2f ms   (%6.1f us per step)" % (s_py*1000, s_py/steps*1e6))
    print("  C++    : %10.2f ms   (%6.1f us per step)   %s" % (s_cpp*1000, s_cpp/steps*1e6, os.path.relpath(exe, HERE)))
    if V_py.shape != V_cpp.shape:
        raise SystemExit("Different result shapes %s vs %s: are the two circuits the same?" % (V_py.shape, V_cpp.shape))
    print("  C++ is %.0fx faster\n" % (s_py / s_cpp))

    diff = np.abs(V_py - V_cpp)
    peak = np.abs(V_py).max(axis=0)
    worst = diff.max()
    print("Accuracy (Python vs C++, all %d node voltages at all %d steps)" % (n, steps))
    print("  max |difference|  : %.3e V" % worst)
    print("  RMS difference    : %.3e V" % np.sqrt(np.mean((V_py - V_cpp)**2)))
    print("  relative to peak  : %.1e   (peak |V| = %.1f V)" % (worst / peak.max(), peak.max()))
    print("  identical values  : %.2f %%" % (100.0*np.mean(V_py == V_cpp)))
    worst_rel_I = 0.0
    if cn_py == cn_cpp and I_py.shape == I_cpp.shape and I_py.size:
        # branch currents (and machine speed, angle, power, torque): currents are compared with the largest
        # current in the circuit (a current that is almost zero, e.g. at an open line end, is all round-off);
        # machine quantities ([pu], [deg]) with their own peak
        dI = np.abs(I_py - I_cpp).max(axis=0)
        pk = np.abs(I_py).max(axis=0)
        is_current = np.array(["[" not in nm for nm in cn_py])
        ref = np.where(is_current, pk[is_current].max() if is_current.any() else 1.0, np.maximum(pk, 1e-30))
        rel = dI/ref
        k = int(np.argmax(rel))
        worst_rel_I = rel[k]
        print("  branch currents   : %d signals, max |difference| %.1e of the largest current (worst: %s)"
              % (len(cn_py), worst_rel_I, cn_py[k]))
    elif cn_py != cn_cpp:
        print("  branch currents   : the two versions record different signals (%d vs %d)" % (len(cn_py), len(cn_cpp)))
    order = np.argsort(-diff.max(axis=0))
    rows = range(n) if n <= 12 else order[:5]
    print("\n  %s" % ("Node   peak |V| (V)   max |Python - C++| (V)" if n <= 12 else
                      "Nodes with the largest difference:\n  Node   peak |V| (V)   max |Python - C++| (V)"))
    for k in rows:
        print("  V%-4d  %12.2f   %22.3e" % (k + 1, peak[k], diff[:, k].max()))
    # Round-off is amplified by the conditioning of the network matrix: switches and diodes (on 1e-3 ohm,
    # off 1e6 ohm) make it ~1e9, so 1e-6 of the peak is still round-off; a real difference (e.g. a diode
    # switching one step earlier) would be of the order of the signal itself.
    agree = worst <= 1e-6 * peak.max() and worst_rel_I <= 1e-6
    print("\n%s" % ("The two versions agree to within floating-point round-off." if agree
                     else "The two versions DIFFER by more than floating-point round-off."))

    if args.plot:
        import matplotlib.pyplot as plt
        # Small networks: every node. Large ones: the 4 nodes with the largest
        # difference and the 4 with the largest voltage swing.
        if n <= 12:
            sel = list(range(n))
        else:
            sel = list(dict.fromkeys(list(order[:4]) + list(np.argsort(-peak)[:4])))
        m = len(sel)
        fig, axes = plt.subplots(m, 2, sharex=True, figsize=(13, min(2.2*m, 1.4*m + 2)), squeeze=False,
                                 gridspec_kw={"width_ratios": [3, 1]})
        for r, k in enumerate(sel):
            axes[r, 0].plot(t_py*1000, V_py[:, k], lw=2.5, alpha=0.5, label="Python")
            axes[r, 0].plot(t_cpp*1000, V_cpp[:, k], lw=1, ls="--", label="C++")
            axes[r, 0].set_ylabel("V%d (V)" % (k + 1))
            axes[r, 1].plot(t_py*1000, V_py[:, k] - V_cpp[:, k], lw=0.8, color="tab:red")
            for ax in axes[r]:
                ax.grid(True, alpha=0.3)
        axes[0, 0].set_title("Node voltages: Python vs C++" + ("" if n <= 12 else " (selected nodes)"))
        axes[0, 0].legend(loc="upper right", fontsize=8)
        axes[0, 1].set_title("Python - C++ (V)")
        axes[-1, 0].set_xlabel("Time (ms)"); axes[-1, 1].set_xlabel("Time (ms)")
        fig.tight_layout()
        if args.save:
            fig.savefig(args.save, dpi=100)
            print("Saved", args.save)
        else:
            plt.show()


if __name__ == "__main__":
    main()
