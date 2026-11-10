import math
import sys
import emtcls
import config
import elements as el
import dataloader as dl


def refactor(EMTDC):
    # Form the conductance matrix, divide it into GUU, GUK, GKU, GKK
    # and LU-decompose GUU. Only needed at the start and when a switch/fault
    # or a non-linear element changes state, because G is constant otherwise.
    EMTDC.formG()
    EMTDC.Gdivide()
    EMTDC.LU()


# Re-solve a step at most this many times while non-linear elements change state
MAX_ITERATIONS = 50


def run(netlist_path=None):
    print("\nStart running the simulation..... \n")
    Time=config.srtTime
    #Use a netlist file if given, otherwise the circuit in dataloader.py
    if netlist_path:
        import netlist
        dl.elemet_list = netlist.load(netlist_path)
    #Initialize the network
    EMTDC=emtcls.Network()
    #Set the initial switch/fault states and factorise G
    EMTDC.updateSwitches(Time)
    refactor(EMTDC)
    EMTDC.unconverged = 0

    if config.chatter or config.interp:
        run_with_events(EMTDC)
        finish(EMTDC)
        return

    #Enter the main time loop
    # half a step of tolerance: Time is accumulated as Time += Dt and can land just below stpTime
    while Time<config.stpTime-0.5*config.Dt:
        #Divide node voltage vector into VU and VK
        EMTDC.Vdivide()
        #Advance one time step
        Time=Time+config.Dt
        #Apply/clear faults; rebuild G if anything switched
        if EMTDC.updateSwitches(Time):
            refactor(EMTDC)
        #Update the voltage sources
        EMTDC.Vkupdate(Time)
        #Calculate the history current of each branch
        EMTDC.calcBrnHistory(Time)
        #Calculate the current injection at each node
        EMTDC.calcinjection()
        #Divide IH in to IU and IK
        EMTDC.Idivide()
        #Calculate new IU
        EMTDC.calIUnew()
        #Calculate new VU
        EMTDC.calcnewV()
        #Reconstruct node voltage vector
        EMTDC.reconstruct_V()
        #Non-linear elements (diodes, arresters, saturation): re-solve until their states agree
        it = 0
        while EMTDC.checkNonlinear(Time):
            it += 1
            if it > MAX_ITERATIONS:
                EMTDC.unconverged += 1
                break
            EMTDC.resolve(Time)
        #Calculate branch currents of each element
        EMTDC.calcNewbranchI(Time)
        #Record the voltages of all nodes
        EMTDC.recordv(Time)

    finish(EMTDC)


def finish(EMTDC):
    if EMTDC.unconverged:
        print("Warning: non-linear elements did not settle within %d iterations in %d steps"
              % (MAX_ITERATIONS, EMTDC.unconverged))
    EMTDC.plotv()


def run_with_events(EMTDC):
    """Time loop with switching interpolation and chatter removal (Watson & Arrillaga, section 9.4.1);
    the same algorithm as Network::runWithEvents in src/network.cpp.

    Interpolation: after a trapezoidal step, the earliest switching inside it (a switch time, a
    breaker current zero, a diode or thyristor turning on or off) is found; the whole solution is
    linearly interpolated back to that instant, the element switches there and G is refactorised.

    Chatter removal (critical damping adjustment): after every switching the next two steps are
    backward-Euler half steps of Dt/2. They have the same conductances as the trapezoidal rule, so
    G is not changed, but their history currents carry no voltage term, so the trapezoidal rule's
    step-by-step oscillation of inductor voltages and capacitor currents never starts. Valves that
    must turn on right after a switching (a free-wheeling diode taking over an inductor current)
    do so in the first half step.

    The solution then runs on a time grid shifted by the switching instant; the next trapezoidal
    step is interpolated back onto the regular grid, where the results are recorded. Grid points
    passed during the half steps are recorded by interpolating (or extrapolating) between the two
    half-step solutions, which are both after the switching.
    """
    dt, t0 = config.Dt, config.srtTime
    nsteps = int(round((config.stpTime - t0)/dt))
    eps = 1e-6
    a = t0                 # time of the present solution (not always on the grid)
    k_rec = 0              # grid points recorded so far
    P, tP = EMTDC.save(), a   # last accepted solution point
    be_left = 0            # backward-Euler half steps still to take after a switching
    stall = 0              # switchings without progress in time

    def on_grid(t):
        x = (t - t0)/dt
        return abs(x - round(x)) <= eps

    def record_to(S, tS):
        # record the grid points up to tS, interpolating (or extrapolating) between P and S
        nonlocal k_rec
        while k_rec < nsteps:
            tk = t0 + (k_rec + 1)*dt
            if tk > tS + eps*dt:
                break
            al = 1.0 if tS - tP <= 1e-12*dt else (tk - tP)/(tS - tP)
            if abs(al - 1.0) <= 1e-12:
                EMTDC.recordv(tk)
            else:
                EMTDC.load(P + al*(S - P))
                EMTDC.recordv(tk)
                EMTDC.load(S)
            k_rec += 1

    while k_rec < nsteps:
        be = be_left > 0
        h = 0.5*dt if be else dt
        config.step, config.euler = h, be
        b = a + h
        for obj in EMTDC.events:
            obj.begin_step(a, b)
        need = be or not on_grid(a) or EMTDC.has_valves or any(obj.scheduled_in(a, b) for obj in EMTDC.events)
        Sa = EMTDC.save() if need else None
        fallback = stall > 20     # stuck switching back and forth: settle the valves within the step instead
        EMTDC.solve_step(b, valves=True if fallback else "on" if be else False, max_iterations=MAX_ITERATIONS)
        best, hits = (None, []) if fallback else EMTDC.detect(a, h, config.interp)
        if fallback:
            stall = 0
        if best is None:
            if be:
                be_left -= 1
                S = EMTDC.save()
                if be_left == 0:          # second half step: record the grid points passed since the switching
                    record_to(S, b)
                P, tP, a = S, b, b
                continue
            g = t0 + math.floor((b - t0)/dt + eps)*dt   # last grid point <= b
            if a + eps*dt < g < b - eps*dt:              # off the grid: interpolate back onto it
                EMTDC.load(Sa + ((g - a)/dt)*(EMTDC.save() - Sa))
                a = g
            else:
                a = g if abs(g - b) <= eps*dt else b
            S = EMTDC.save()
            record_to(S, a)
            P, tP = S, a
            continue
        # a switching at te inside the step: interpolate back to it, switch, refactorise
        te = a + best*h
        if best < 1.0 - 1e-12:
            EMTDC.load(Sa + best*(EMTDC.save() - Sa))
        stall = stall + 1 if best <= 1e-9 else 0
        S = EMTDC.save()
        record_to(S, te)
        P, tP = S, te
        changed = False
        for obj in hits:
            changed = obj.apply_event(te) or changed
        if changed:
            refactor(EMTDC)
            if config.chatter:
                be_left = 2
        a = te
    config.step, config.euler = dt, False
