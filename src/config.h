#pragma once

// Simulation settings. The defaults can be changed per circuit with a netlist line
//     .tran dt tstop
// which the netlist reader applies before it builds the elements (their companion
// models depend on the time step).
namespace config {

constexpr double defaultDt = 100e-6;               // time step (s)
constexpr double defaultStop = 1000 * defaultDt;   // stop time (s)

inline double Dt = defaultDt;                      // time step (s)
inline double srtTime = 0.0;                       // start time (s)
inline double stpTime = srtTime + defaultStop;     // stop time (s)

}  // namespace config
