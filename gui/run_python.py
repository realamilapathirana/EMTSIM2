"""Run the Python EMTSim on a netlist file and print the results as JSON.

Used by gui/server.py:   python gui/run_python.py circuit.net
"""
import contextlib
import io
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(path):
    import matplotlib
    matplotlib.use("Agg")
    import elements as el
    import emtcls
    import main as sim

    nets = []
    emtcls.Network.plotv = lambda self: nets.append(self)   # capture instead of plotting
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            t0 = time.perf_counter()
            sim.run(path)
            sim_ms = (time.perf_counter() - t0)*1000.0
    except Exception as e:  # report simulator errors to the editor
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e), "log": log.getvalue()[-4000:]}))
        return
    net = nets[0]
    V = [[float(row[k]) for row in net.trace] for k in range(net.numNodes)]
    if not all(math.isfinite(x) for v in V for x in v):
        # scipy only warns on a singular matrix and returns NaN/inf
        print(json.dumps({"error": "The results are not finite: the conductance matrix is singular "
                                   "(is there a floating node, or a node connected only through ideal sources?)",
                          "log": log.getvalue()[-4000:]}))
        return
    faults = [[o.t_apply, o.t_clear] for o in net.comp_list if isinstance(o, el.Fault)]
    switches = [t for o in net.comp_list if isinstance(o, el.Switch) and not isinstance(o, el.Fault) for t in o.t_switch]
    events = [l for l in log.getvalue().splitlines() if l.startswith("t = ") or l.startswith("Warning")]
    nI = len(net.current_names)
    I = [[float(row[k]) for row in net.ctrace] for k in range(nI)]
    if not all(math.isfinite(x) for v in I for x in v):
        I = [[x if math.isfinite(x) else 0.0 for x in v] for v in I]
    print(json.dumps({
        "names": ["V%d" % (k + 1) for k in range(net.numNodes)],
        "t": list(net.time), "V": V,
        "cnames": list(net.current_names), "I": I,
        "events": {"faults": faults, "switches": switches},
        "sim_ms": sim_ms, "log": "\n".join(events),
    }))


if __name__ == "__main__":
    main(sys.argv[1])
