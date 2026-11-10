@echo off
rem Build EMTSim, run the simulation and plot the node voltages.
rem Usage: run.bat                         circuit in src\circuit.cpp
rem        run.bat circuits\grid100.net    circuit from a netlist file
rem        run.bat circuits\grid100.net --chatter=off --interp=off
rem                                        override the netlist's .options (chatter removal, interpolation)
setlocal
cd /d "%~dp0"

call "%~dp0build.bat" || exit /b 1
"%~dp0build\emtsim.exe" %* || exit /b 1

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0plot.py"
) else (
    python "%~dp0plot.py"
)
