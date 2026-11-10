#pragma once

// Simulation settings. The defaults can be changed per circuit with netlist lines
//     .tran dt tstop
//     .options chatter=on|off interp=on|off
// which the netlist reader applies before it builds the elements (their companion
// models depend on the time step).
//
// chatter: chatter removal by critical damping adjustment: two backward-Euler half
//          steps after every switching (Watson & Arrillaga, section 9.4.1)
// interp:  interpolate to the exact instant of switching (switch times between time
//          points, breaker current zeros, diode/thyristor turn-on and turn-off)
// With both off, the solver is the plain trapezoidal-rule method.
namespace config {

constexpr double defaultDt = 100e-6;               // time step (s)
constexpr double defaultStop = 1000 * defaultDt;   // stop time (s)

inline double Dt = defaultDt;                      // time step (s)
inline double srtTime = 0.0;                       // start time (s)
inline double stpTime = srtTime + defaultStop;     // stop time (s)

constexpr bool defaultChatter = true;
constexpr bool defaultInterp = true;
inline bool chatter = defaultChatter;              // chatter removal
inline bool interp = defaultInterp;                // switching interpolation

// The step being taken (set by the time loop): its length, and whether it is a backward-Euler
// half step (Dt/2, same conductances as the trapezoidal rule, different history currents)
inline double step = defaultDt;
inline bool euler = false;

}  // namespace config
