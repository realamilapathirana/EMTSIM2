"""The network solver of the Python EMTSim: Dommel's nodal method (same algorithm as src/network.cpp).

Every time step the network is a resistive circuit  G v = i_h.  Each element adds
its conductance block (stamp) and history currents. Nodes are split into unknown
(U) and known (K, fixed by ideal sources and machine EMFs) nodes:

    G_UU v_U = i_U - G_UK v_K

G_UU is LU-factorised at the start and again only when a switch operates or a
non-linear element changes state; non-linear elements (diodes, arresters,
saturation) are handled by re-solving the step until their states agree.
"""
import numpy as np
import config
import elements as el
import dataloader as dl
import matplotlib.pyplot as plt
import scipy.linalg as la


class Network:
    def __init__(self):

        self.comp_list = dl.elemet_list

        self.totalNodes = 0
        for obj in self.comp_list:
            for n in obj.nodes:
                if n < 0:
                    raise ValueError("Negative node number in " + obj.name)
                self.totalNodes = max(self.totalNodes, n)
        user = getattr(dl.elemet_list, "user_nodes", None)
        # nodes above user_nodes are internal nodes of composite elements (not recorded)
        self.numNodes = self.totalNodes if user is None else min(user, self.totalNodes)

        # Known nodes: voltages fixed by ideal sources and machine EMFs
        known = []
        for obj in self.comp_list:
            for p in obj.known_terminals():
                node = obj.nodes[p]
                if node == 0:
                    raise ValueError(obj.name + ": a known (ideal source) voltage cannot be on ground")
                if node in known:
                    raise ValueError("Two ideal voltage sources on node %d" % node)
                known.append(node)

        # Internal node ordering: unknown nodes first, then known nodes, so that G can
        # be partitioned into G_UU, G_UK, G_KU, G_KK regardless of how the nodes are numbered.
        known_set = set(known)
        unknown = [n for n in range(1, self.totalNodes + 1) if n not in known_set]
        self.order = unknown + known
        self.idx = {n: i for i, n in enumerate(self.order)}
        self.idx[0] = -1

        self.src_cont = len(known)
        self.unknownNodes = self.totalNodes - self.src_cont
        self.known_idx = []
        self.current_names = []
        for k, obj in enumerate(self.comp_list):
            if not obj.name:                       # same default names as the C++ version
                obj.name = obj.type + str(k + 1)
            obj.idx = [self.idx[n] for n in obj.nodes]
            self.known_idx.append([self.idx[obj.nodes[p]] - self.unknownNodes for p in obj.known_terminals()])
            self.current_names += obj.current_names()
        self.hist = [np.zeros(obj.size()) for obj in self.comp_list]
        self.nonlinear = [obj for obj in self.comp_list if obj.nonlinear]   # state can change with the solution

        self.G = np.zeros((self.totalNodes, self.totalNodes))
        self.Vn = np.zeros((self.totalNodes, 1))
        self.I_H = np.zeros((self.totalNodes, 1))
        self.factorisations = 0
        self.resolves = 0

        self.time = []
        self.trace = []       # one row per time step: voltages of nodes 1..numNodes
        self.ctrace = []      # one row per time step: branch currents

        print("No of ideal sources", self.src_cont, "\n")
        print("No of unknown nodes", self.unknownNodes, "\n")

    def updateSwitches(self, TheTime):
        '''Scheduled switching. Returns True if any conductance changed (G must be rebuilt).'''
        changed = False
        for obj in self.comp_list:
            changed = obj.time_event(TheTime) or changed
        return changed

    def formG(self):
        self.G = np.zeros((self.totalNodes, self.totalNodes))
        for obj in self.comp_list:
            g = obj.stamp()
            ix = obj.idx
            for i in range(len(ix)):
                if ix[i] < 0:
                    continue
                for j in range(len(ix)):
                    if ix[j] >= 0 and g[i][j] != 0.0:
                        self.G[ix[i], ix[j]] += g[i][j]
        if self.totalNodes <= 10:
            print(self.G)

    def Gdivide(self):
        u, n = self.unknownNodes, self.totalNodes
        self.G_UU = self.G[0:u, 0:u]
        self.G_UK = self.G[0:u, u:n]
        self.G_KU = self.G[u:n, 0:u]
        self.G_KK = self.G[u:n, u:n]

    def LU(self):
        # Keep the full factorisation (L, U and the pivots) for lu_solve
        self.G_UU_LU = la.lu_factor(self.G_UU)
        self.factorisations += 1

    def Vdivide(self):
        self.V_K = self.Vn[self.unknownNodes:self.totalNodes]
        self.V_U = self.Vn[0:self.unknownNodes]

    def Vkupdate(self, TheTime):
        for obj, ki in zip(self.comp_list, self.known_idx):
            if ki:
                for k, e in zip(ki, obj.known_voltages(TheTime)):
                    self.V_K[k] = e

    def calcBrnHistory(self, TheTime):
        for n, obj in enumerate(self.comp_list):
            self.hist[n] = obj.history(TheTime)

    def calcinjection(self):
        self.I_H = np.zeros((self.totalNodes, 1))
        # Each element draws i = g v + h from its terminals, so h is subtracted at each terminal node
        for obj, h in zip(self.comp_list, self.hist):
            for j, ix in enumerate(obj.idx):
                if ix >= 0:
                    self.I_H[ix] -= h[j]

    def Idivide(self):
        self.I_K = self.I_H[self.unknownNodes:self.totalNodes]
        self.I_U = self.I_H[0:self.unknownNodes]

    def calIUnew(self):
        self.I_U_new = self.I_U - np.matmul(self.G_UK, self.V_K)

    def calcnewV(self):
        self.V_U = la.lu_solve(self.G_UU_LU, self.I_U_new)

    def reconstruct_V(self):
        self.Vn = np.concatenate([self.V_U, self.V_K])

    def _terminal_voltages(self, obj):
        return [self.Vn[ix, 0] if ix >= 0 else 0.0 for ix in obj.idx]

    def checkNonlinear(self, TheTime):
        '''State changes of non-linear elements; True -> re-solve the step.'''
        changed = False
        for obj in self.nonlinear:
            changed = obj.check(TheTime, self._terminal_voltages(obj)) or changed
        return changed

    def resolve(self, TheTime):
        '''Refactorise and solve the step again (after checkNonlinear).'''
        self.formG(); self.Gdivide(); self.LU()
        self.calcBrnHistory(TheTime); self.calcinjection(); self.Idivide(); self.calIUnew()
        self.calcnewV(); self.reconstruct_V()
        self.resolves += 1

    def calcNewbranchI(self, TheTime):
        # Current delivered by the known sources into each known node: I = G_KU v_U + G_KK v_K - I_K
        if self.src_cont:
            Iknown = (self.G_KU @ self.V_U + self.G_KK @ self.V_K - self.I_K)[:, 0]
        for obj, ki in zip(self.comp_list, self.known_idx):
            if ki:
                obj.set_known_currents([Iknown[k] for k in ki])
            obj.update(TheTime, self._terminal_voltages(obj))

    def node_voltage(self, node):
        return 0.0 if node == 0 else self.Vn[self.idx[node], 0]

    def recordv(self, TheTime):
        # Store all node voltages in user node order (node 1, 2, ...) and all branch currents
        self.time.append(TheTime)
        self.trace.append([self.Vn[self.idx[n], 0] for n in range(1, self.numNodes + 1)])
        row = []
        for obj in self.comp_list:
            row += list(obj.currents())
        self.ctrace.append(row)

    def plotv(self):
        from plot import plot_nodes
        faults = [(o.t_apply, o.t_clear) for o in self.comp_list if isinstance(o, el.Fault)]
        switches = [ts for o in self.comp_list
                    if isinstance(o, el.Switch) and not isinstance(o, el.Fault) for ts in o.t_switch]
        plt.close('all')
        plot_nodes(np.array(self.time)*1000.0, np.array(self.trace),
                   ["V%d" % (n + 1) for n in range(self.numNodes)], faults, switches)
        plt.show()
