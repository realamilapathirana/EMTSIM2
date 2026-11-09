# Simulation settings. The defaults can be changed per circuit with a netlist line
#     .tran dt tstop
# which netlist.py applies before it builds the elements (their companion models
# depend on the time step).
defaultDt=100e-6
defaultStop=1000*defaultDt

Dt=defaultDt
srtTime=0.0
stpTime=srtTime+defaultStop
