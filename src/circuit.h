#pragma once

// Helper for describing a circuit as a list of elements.
// Node 0 is ground; other nodes are numbered 1, 2, 3, ...
// Netlist files are read into the same structure by loadNetlist() (netlist.h).

#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "elements.h"

class Circuit {
public:
    void addR(int from, int to, double ohm) { add<RLC>('R', from, to, ohm); }
    void addL(int from, int to, double henry) { add<RLC>('L', from, to, henry); }
    void addC(int from, int to, double farad) { add<RLC>('C', from, to, farad); }

    // resistance > 0: Norton source; resistance omitted/0: ideal source (one terminal grounded)
    void addSource(int from, int to, double magnitude, double angle_deg, double frequency, double resistance = 0.0) {
        add<Source>(from, to, magnitude, angle_deg, frequency, resistance);
    }

    // Breaker starting in state `closed`, toggling at each time in `times`
    Switch& addSwitch(int from, int to, bool closed, std::vector<double> times, double Ron = 0.01, double Roff = 1.0e6) {
        return add<Switch>(from, to, closed, std::move(times), Ron, Roff);
    }

    // Fault applied at t_apply, cleared at t_clear (std::nullopt = permanent)
    void addFault(int from, int to, double t_apply, std::optional<double> t_clear, double Ron = 0.01, double Roff = 1.0e6) {
        add<Fault>(from, to, t_apply, t_clear, Ron, Roff);
    }

    // Add any element; it gets a default name (type + number) unless it already has one
    template <class T, class... Args>
    T& add(Args&&... args) {
        auto p = std::make_unique<T>(std::forward<Args>(args)...);
        T& ref = *p;
        if (ref.name.empty()) ref.name = ref.type + std::to_string(elements.size() + 1);
        elements.push_back(std::move(p));
        return ref;
    }

    std::vector<std::unique_ptr<Element>> elements;
    int userNodes = -1;   // nodes above this are internal nodes of composite elements (-1: none)
};

// The circuit to simulate. Defined in circuit.cpp: edit that file to change it.
Circuit buildCircuit();
