# Simulation settings. The defaults can be changed per circuit with netlist lines
#     .tran dt tstop
#     .options chatter=on|off interp=on|off
# which netlist.py applies before it builds the elements (their companion models
# depend on the time step).
#
# chatter: chatter removal by critical damping adjustment: two backward-Euler half
#          steps after every switching (Watson & Arrillaga, section 9.4.1)
# interp:  interpolate to the exact instant of switching (switch times between time
#          points, breaker current zeros, diode/thyristor turn-on and turn-off)
# With both off, the solver is the plain trapezoidal-rule method.
defaultDt=100e-6
defaultStop=1000*defaultDt

Dt=defaultDt
srtTime=0.0
stpTime=srtTime+defaultStop

# The step being taken (set by the time loop): its length, and whether it is a backward-Euler
# half step (Dt/2, same conductances as the trapezoidal rule, different history currents)
step=Dt
euler=False

defaultChatter=True
defaultInterp=True
chatter=defaultChatter
interp=defaultInterp
