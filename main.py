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

    if EMTDC.unconverged:
        print("Warning: non-linear elements did not settle within %d iterations in %d steps"
              % (MAX_ITERATIONS, EMTDC.unconverged))
    EMTDC.plotv()


if __name__ == "__main__":
    # python main.py                       -> circuit in dataloader.py
    # python main.py circuits/grid100.net  -> circuit from a netlist file
    run(sys.argv[1] if len(sys.argv) > 1 else None)
