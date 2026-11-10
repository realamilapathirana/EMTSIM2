/*
 * EMTSim schematic model -> netlist.
 *
 * Used by the circuit editor in the browser (window.Schematic) and by the
 * tests under Node (require('./schematic.js')).
 *
 * Model (all coordinates in grid units):
 *   { v: 1, phases: 1 | 3,
 *     components: [{ id, type, name, x, y, rot, params: { ... strings ... } }],
 *     wires:      [{ x1, y1, x2, y2 }] }
 *
 * Two-terminal components run from terminal a = (x, y) to terminal b, LEN grid
 * units away in the direction given by rot (0 = right, 90 = down, 180 = left,
 * 270 = up). Terminal a is the netlist "from" node, b the "to" node; a voltage
 * source raises b above a. GND and the 3-phase fault F3 have a single terminal
 * at (x, y).
 *
 * Three-phase mode (phases: 3): wires and nodes carry phases a, b, c. Drawing
 * node k becomes netlist nodes 3k-2, 3k-1, 3k (phases a, b, c); ground is node 0
 * for every phase. Each 3-phase component is written as three single-phase
 * elements, one per phase, so the simulators need no changes. There is no
 * mutual coupling between phases.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Schematic = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const LEN = 4;
  const DIRS = { 0: [1, 0], 90: [0, 1], 180: [-1, 0], 270: [0, -1] };
  const PH = ['a', 'b', 'c'];
  const STATE = { kind: 'select', options: ['closed', 'open'], def: 'closed' };
  const POLES = { key: 'mode', kind: 'select', options: ['together', 'independent'], def: 'together' };
  const OPENS = { key: 'opens', label: 'Opening', kind: 'select', options: ['at the time', 'at current zero'], def: 'at the time' };
  const XFPARAMS = [
    { key: 'S', label: 'Rating', unit: 'VA', def: '1M' },
    { key: 'v1', label: 'Primary voltage (rms, line-to-line for 3φ)', unit: 'V', def: '11k' },
    { key: 'v2', label: 'Secondary voltage (rms, line-to-line for 3φ)', unit: 'V', def: '400' },
    { key: 'freq', label: 'Frequency', unit: 'Hz', def: '50' },
    { key: 'x', label: 'Leakage reactance', unit: 'pu', def: '0.06' },
    { key: 'r', label: 'Winding resistance', unit: 'pu', def: '0.01' },
    { key: 'im', label: 'Magnetising current (0 = none)', unit: '%', def: '1' },
    { key: 'knee', label: 'Saturation knee (blank = linear core)', unit: 'pu', def: '', optional: true },
    { key: 'lsat', label: 'Saturated inductance (blank = 2 x leakage)', unit: 'pu', def: '', optional: true }];
  const MOVPARAMS = [
    { key: 'vref', label: 'Reference voltage (peak)', unit: 'V', def: '1k' },
    { key: 'iref', label: 'Current at the reference voltage', unit: 'A', def: '1k' },
    { key: 'q', label: 'Exponent q (i = Iref (v/Vref)^q)', unit: '', def: '26' }];
  const RONOFF = [
    { key: 'ron', label: 'On resistance', unit: 'Ω', def: '1m' },
    { key: 'roff', label: 'Off resistance', unit: 'Ω', def: '1meg' }];

  const TYPES = {
    R: { label: 'Resistor', prefix: 'R', params: [
      { key: 'value', label: 'Resistance', unit: 'Ω', def: '10' }] },
    L: { label: 'Inductor', prefix: 'L', params: [
      { key: 'value', label: 'Inductance', unit: 'H', def: '10m' }] },
    C: { label: 'Capacitor', prefix: 'C', params: [
      { key: 'value', label: 'Capacitance', unit: 'F', def: '10u' }] },
    V: { label: 'Voltage source', prefix: 'V', params: [
      { key: 'mag', label: 'Peak voltage', unit: 'V', def: '325' },
      { key: 'angle', label: 'Angle', unit: '°', def: '0' },
      { key: 'freq', label: 'Frequency', unit: 'Hz', def: '50' },
      { key: 'r', label: 'Internal resistance (blank or 0 = ideal)', unit: 'Ω', def: '0.1', optional: true },
      { key: 'l', label: 'Series inductance (blank = none; needs one end on ground)', unit: 'H', def: '', optional: true }] },
    SW: { label: 'Switch', prefix: 'SW', params: [
      Object.assign({ key: 'state', label: 'Initial state' }, STATE),
      { key: 'times', label: 'Switching times (toggles at each)', unit: 's', kind: 'list', def: '50m', optional: true },
      OPENS] },
    F: { label: 'Fault', prefix: 'F', params: [
      { key: 't_apply', label: 'Applied at', unit: 's', def: '20m' },
      { key: 't_clear', label: 'Cleared at (blank = permanent)', unit: 's', def: '40m', optional: true }] },
    GND: { label: 'Ground', prefix: 'GND', params: [] },
    PI: { label: 'Line (nominal pi)', prefix: 'LN', params: [
      { key: 'r', label: 'Series resistance (total)', unit: 'Ω', def: '1' },
      { key: 'l', label: 'Series inductance (total)', unit: 'H', def: '10m' },
      { key: 'c', label: 'Shunt capacitance (total, half at each end)', unit: 'F', def: '1u' }] },
    TL: { label: 'Line (travelling wave, Bergeron)', prefix: 'TL', params: [
      { key: 'zc', label: 'Surge impedance', unit: 'Ω', def: '400' },
      { key: 'tau', label: 'Travel time (at least one time step)', unit: 's', def: '1m' },
      { key: 'r', label: 'Series resistance (total)', unit: 'Ω', def: '0', optional: true }] },
    XF: { label: 'Transformer', prefix: 'T', params: XFPARAMS },
    MOV: { label: 'Surge arrester', prefix: 'A', params: MOVPARAMS },
    D: { label: 'Diode', prefix: 'D', params: RONOFF.concat([{ key: 'vf', label: 'Forward voltage', unit: 'V', def: '0' }]) },
    THY: { label: 'Thyristor', prefix: 'TH', params: [
      { key: 'alpha', label: 'Firing angle', unit: '°', def: '30' },
      { key: 'freq', label: 'Frequency of the gate timing', unit: 'Hz', def: '50' },
      { key: 'ref', label: 'Reference angle (gate phase = 360 f t + ref)', unit: '°', def: '0' },
      { key: 'width', label: 'Gate pulse width', unit: '°', def: '120' }].concat(RONOFF) },

    // ---- three-phase
    R3: { label: 'Resistor (3-phase)', prefix: 'R', three: true, base: 'R', params: [
      { key: 'value', label: 'Resistance per phase', unit: 'Ω', def: '10' }] },
    L3: { label: 'Inductor (3-phase)', prefix: 'L', three: true, base: 'L', params: [
      { key: 'value', label: 'Inductance per phase', unit: 'H', def: '10m' }] },
    C3: { label: 'Capacitor (3-phase)', prefix: 'C', three: true, base: 'C', params: [
      { key: 'value', label: 'Capacitance per phase', unit: 'F', def: '10u' }] },
    V3: { label: 'Voltage source (3-phase)', prefix: 'V', three: true, params: [
      { key: 'mag', label: 'Peak phase voltage (line to ground)', unit: 'V', def: '325' },
      { key: 'angle', label: 'Angle of phase a (b = a − 120°, c = a + 120°)', unit: '°', def: '0' },
      { key: 'freq', label: 'Frequency', unit: 'Hz', def: '50' },
      { key: 'r', label: 'Internal resistance R1 (blank or 0 = ideal)', unit: 'Ω', def: '0.1', optional: true },
      { key: 'l1', label: 'Source inductance L1 (blank = none; needs the − end on ground)', unit: 'H', def: '', optional: true },
      { key: 'r0', label: 'Zero-sequence resistance R0 (blank = R1)', unit: 'Ω', def: '', optional: true },
      { key: 'l0', label: 'Zero-sequence inductance L0 (blank = L1)', unit: 'H', def: '', optional: true }] },
    SW3: { label: 'Switch (3-phase)', prefix: 'SW', three: true, params: [
      Object.assign({}, POLES, { label: 'Poles' }),
      Object.assign({ key: 'state', label: 'Initial state', when: 'together' }, STATE),
      { key: 'times', label: 'Switching times (toggles at each)', unit: 's', kind: 'list', def: '50m', optional: true, when: 'together' },
    ].concat(...PH.map((p) => [
      Object.assign({ key: 'state_' + p, label: 'Pole ' + p + ': initial state', when: 'independent' }, STATE),
      { key: 'times_' + p, label: 'Pole ' + p + ': switching times', unit: 's', kind: 'list', def: '50m', optional: true, when: 'independent' }]))
      .concat([OPENS]) },
    F3: { label: 'Fault (3-phase)', prefix: 'F', three: true, single: true, params: [
      { key: 'kind', label: 'Fault type (-g = to ground)', kind: 'select',
        options: ['a-g', 'b-g', 'c-g', 'ab', 'bc', 'ca', 'ab-g', 'bc-g', 'ca-g', 'abc', 'abc-g'], def: 'a-g' },
      Object.assign({}, POLES, { label: 'Timing of the phases' }),
      { key: 't_apply', label: 'Applied at', unit: 's', def: '20m', when: 'together' },
      { key: 't_clear', label: 'Cleared at (blank = permanent)', unit: 's', def: '40m', optional: true, when: 'together' },
    ].concat(...PH.map((p) => [
      { key: 't_apply_' + p, label: 'Phase ' + p + ': applied at', unit: 's', def: '20m', when: 'independent' },
      { key: 't_clear_' + p, label: 'Phase ' + p + ': cleared at (blank = permanent)', unit: 's', def: '40m', optional: true, when: 'independent' }])) },
    PI3: { label: 'Line 3φ (nominal pi)', prefix: 'LN', three: true, params: [
      { key: 'r1', label: 'R1 positive sequence (total)', unit: 'Ω', def: '1' },
      { key: 'l1', label: 'L1 positive sequence (total)', unit: 'H', def: '10m' },
      { key: 'c1', label: 'C1 positive sequence (total)', unit: 'F', def: '1u' },
      { key: 'r0', label: 'R0 zero sequence (blank = R1)', unit: 'Ω', def: '', optional: true },
      { key: 'l0', label: 'L0 zero sequence (blank = L1)', unit: 'H', def: '', optional: true },
      { key: 'c0', label: 'C0 zero sequence (blank = C1)', unit: 'F', def: '', optional: true }] },
    RL3: { label: 'Coupled R-L 3φ', prefix: 'Z', three: true, params: [
      { key: 'r1', label: 'R1 positive sequence', unit: 'Ω', def: '1' },
      { key: 'l1', label: 'L1 positive sequence', unit: 'H', def: '10m' },
      { key: 'r0', label: 'R0 zero sequence (blank = R1)', unit: 'Ω', def: '', optional: true },
      { key: 'l0', label: 'L0 zero sequence (blank = L1)', unit: 'H', def: '', optional: true }] },
    TL3: { label: 'Line 3φ (travelling wave, Bergeron)', prefix: 'TL', three: true, params: [
      { key: 'z1', label: 'Z1 surge impedance, positive sequence', unit: 'Ω', def: '300' },
      { key: 'tau1', label: 'Travel time, positive sequence', unit: 's', def: '1m' },
      { key: 'z0', label: 'Z0 surge impedance, zero sequence', unit: 'Ω', def: '600' },
      { key: 'tau0', label: 'Travel time, zero sequence', unit: 's', def: '1.3m' },
      { key: 'r1', label: 'R1 series resistance (total)', unit: 'Ω', def: '0', optional: true },
      { key: 'r0', label: 'R0 series resistance (total, blank = R1)', unit: 'Ω', def: '', optional: true }] },
    XF3: { label: 'Transformer 3φ', prefix: 'T', three: true, params: [
      { key: 'conn', label: 'Vector group', kind: 'select', options: ['YNyn0', 'YNd1', 'YNd11', 'Dyn1', 'Dyn11', 'Yy0', 'Dd0'], def: 'YNd1' }]
      .concat(XFPARAMS) },
    MOV3: { label: 'Surge arrester 3φ', prefix: 'A', three: true, params: MOVPARAMS },
    SM: { label: 'Synchronous machine', prefix: 'G', three: true, single: true, params: [
      { key: 'S', label: 'Rating', unit: 'VA', def: '20M' },
      { key: 'v', label: 'Voltage (rms, line-to-line)', unit: 'V', def: '11k' },
      { key: 'freq', label: 'Frequency', unit: 'Hz', def: '50' },
      { key: 'H', label: 'Inertia constant H', unit: 's', def: '3' },
      { key: 'xd2', label: 'Subtransient reactance xd"', unit: 'pu', def: '0.2' },
      { key: 'ra', label: 'Armature resistance', unit: 'pu', def: '0.003' },
      { key: 'E', label: 'Internal EMF', unit: 'pu', def: '1.1' },
      { key: 'delta0', label: 'Initial rotor angle', unit: '°', def: '20' },
      { key: 'Pm', label: 'Mechanical power', unit: 'pu', def: '0.8' },
      { key: 'd', label: 'Damping', unit: 'pu', def: '2' }] },
    IM: { label: 'Induction motor', prefix: 'M', three: true, single: true, params: [
      { key: 'S', label: 'Rating', unit: 'VA', def: '2M' },
      { key: 'v', label: 'Voltage (rms, line-to-line)', unit: 'V', def: '11k' },
      { key: 'freq', label: 'Frequency', unit: 'Hz', def: '50' },
      { key: 'poles', label: 'Poles', unit: '', def: '4' },
      { key: 'rs', label: 'Stator resistance', unit: 'pu', def: '0.01' },
      { key: 'xls', label: 'Stator leakage reactance', unit: 'pu', def: '0.1' },
      { key: 'rr', label: 'Rotor resistance', unit: 'pu', def: '0.04' },
      { key: 'xlr', label: 'Rotor leakage reactance', unit: 'pu', def: '0.1' },
      { key: 'xm', label: 'Magnetising reactance', unit: 'pu', def: '3' },
      { key: 'H', label: 'Inertia constant H', unit: 's', def: '0.3' },
      { key: 'Tload', label: 'Load torque at rated speed (~ speed²)', unit: 'pu', def: '0.6' },
      { key: 'speed0', label: 'Initial speed', unit: 'pu', def: '0' }] },
  };

  // Single-phase <-> three-phase equivalents (used when the drawing's mode is changed)
  const TO3 = { R: 'R3', L: 'L3', C: 'C3', V: 'V3', SW: 'SW3', F: 'F3', PI: 'PI3', TL: 'TL3', XF: 'XF3', MOV: 'MOV3' };
  const TO1 = { R3: 'R', L3: 'L', C3: 'C', V3: 'V', SW3: 'SW', F3: 'F', PI3: 'PI', TL3: 'TL', XF3: 'XF', MOV3: 'MOV' };
  const isThree = (type) => !!(TYPES[type] && TYPES[type].three);

  // Parameters shown/used for a component: those whose 'when' matches its pole/timing mode
  function activeParams(c) {
    const mode = (c.params && c.params.mode) || 'together';
    return TYPES[c.type].params.filter((p) => !p.when || p.when === mode);
  }

  // ------------------------------------------------------------ values

  const SI = { f: 1e-15, p: 1e-12, n: 1e-9, u: 1e-6, 'µ': 1e-6, m: 1e-3, k: 1e3, M: 1e6, meg: 1e6, G: 1e9 };

  // "3m" -> 0.003, "30uF" -> 3e-5, "1.5k" -> 1500, "20ms" -> 0.02. Empty -> null, invalid -> NaN.
  function parseValue(s) {
    s = String(s == null ? '' : s).trim();
    if (!s) return null;
    const m = s.match(/^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(meg|[fpnuµmkMG])?\s*[A-Za-zΩ°µ]*$/);
    if (!m) return NaN;
    return parseFloat(m[1]) * (m[2] ? SI[m[2]] : 1);
  }

  function parseList(s) {
    const parts = String(s == null ? '' : s).split(/[,;\s]+/).filter(Boolean);
    return parts.map(parseValue);
  }

  // Netlist number format: up to 12 significant digits, shortest form
  function fmt(x) {
    return String(Number(x.toPrecision(12)));
  }

  // Display format with SI prefix: 0.003, 'H' -> "3 mH"
  function formatSI(x, unit) {
    if (x == null || !isFinite(x)) return '?';
    if (x === 0) return '0' + (unit ? ' ' + unit : '');
    const prefixes = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p']];
    const a = Math.abs(x);
    let p = prefixes.find(([f]) => a >= f * 0.9999) || prefixes[prefixes.length - 1];
    if (unit === '°' || unit === 'Hz' && a < 1e3) p = [1, ''];
    return String(Number((x / p[0]).toPrecision(4))) + ' ' + p[1] + (unit || '');
  }

  // ------------------------------------------------------------ geometry

  const singleTerminal = (type) => type === 'GND' || !!(TYPES[type] && TYPES[type].single);

  function terminals(c) {
    if (singleTerminal(c.type)) return [[c.x, c.y]];
    const d = DIRS[c.rot || 0];
    return [[c.x, c.y], [c.x + d[0] * LEN, c.y + d[1] * LEN]];
  }

  const key = (p) => p[0] + ',' + p[1];

  // Is point p on segment w (including the end points)?
  function onSegment(p, w) {
    const [x, y] = p;
    const cross = (w.x2 - w.x1) * (y - w.y1) - (w.y2 - w.y1) * (x - w.x1);
    if (Math.abs(cross) > 1e-9) return false;
    return x >= Math.min(w.x1, w.x2) && x <= Math.max(w.x1, w.x2) &&
           y >= Math.min(w.y1, w.y2) && y <= Math.max(w.y1, w.y2);
  }

  // ------------------------------------------------------------ connectivity

  // Groups all connection points into nets. Returns
  //   { pointNet: Map(key -> net index), nets: [{ points: [[x,y]...], terminals: n, ground: bool }],
  //     degree: Map(key -> connection count) }
  function connectivity(model) {
    const parent = new Map();
    const coords = new Map();
    const find = (k) => {
      while (parent.get(k) !== k) { parent.set(k, parent.get(parent.get(k))); k = parent.get(k); }
      return k;
    };
    const add = (p) => { const k = key(p); if (!parent.has(k)) { parent.set(k, k); coords.set(k, p); } return k; };
    const union = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) parent.set(ra, rb); };
    const degree = new Map();
    const bump = (k, n) => degree.set(k, (degree.get(k) || 0) + n);

    for (const c of model.components) for (const p of terminals(c)) bump(add(p), 1);
    for (const w of model.wires) {
      const a = add([w.x1, w.y1]), b = add([w.x2, w.y2]);
      union(a, b); bump(a, 1); bump(b, 1);
    }
    // T-junctions: a terminal or wire end lying on another wire joins it.
    // Points are indexed by row and column, so horizontal and vertical wires only test the
    // points on their own line (fast for large drawings); other wires test every point.
    const byRow = new Map(), byCol = new Map();
    for (const [k, p] of coords) {
      if (!byRow.has(p[1])) byRow.set(p[1], []);
      if (!byCol.has(p[0])) byCol.set(p[0], []);
      byRow.get(p[1]).push(k); byCol.get(p[0]).push(k);
    }
    for (const w of model.wires) {
      const a = key([w.x1, w.y1]), b = key([w.x2, w.y2]);
      const candidates = w.y1 === w.y2 ? byRow.get(w.y1) : w.x1 === w.x2 ? byCol.get(w.x1) : [...coords.keys()];
      for (const k of candidates) {
        if (k !== a && k !== b && onSegment(coords.get(k), w)) { union(k, a); bump(k, 2); }
      }
    }
    // All ground symbols are the same node
    let gnd = null;
    for (const c of model.components) {
      if (c.type !== 'GND') continue;
      const k = key([c.x, c.y]);
      if (gnd === null) gnd = k; else union(k, gnd);
    }

    const rootNet = new Map();
    const nets = [];
    const pointNet = new Map();
    for (const k of parent.keys()) {
      const r = find(k);
      if (!rootNet.has(r)) { rootNet.set(r, nets.length); nets.push({ points: [], terminals: 0, ground: false }); }
      const i = rootNet.get(r);
      nets[i].points.push(coords.get(k));
      pointNet.set(k, i);
    }
    if (gnd !== null) nets[pointNet.get(gnd)].ground = true;
    for (const c of model.components) {
      if (c.type === 'GND') continue;
      for (const p of terminals(c)) nets[pointNet.get(key(p))].terminals++;
    }
    return { pointNet, nets, degree };
  }

  // ------------------------------------------------------------ netlist

  // Returns { text, lines, errors: [], warnings: [], phases, nodeCount (drawing nodes), netlistNodes,
  //           labels: [{node, x, y}], componentNodes: Map(id -> [from, to] drawing nodes),
  //           dangling: [[x,y]...], junctions: [[x,y]...] }
  function buildNetlist(model, opts) {
    opts = opts || {};
    const phases = model.phases === 3 ? 3 : 1;
    const errors = [], warnings = [];
    const { pointNet, nets, degree } = connectivity(model);

    // Number the nets that touch a component (ground = 0), left to right, then top to bottom
    const numbered = nets
      .map((n, i) => ({ i, n }))
      .filter(({ n }) => !n.ground && n.terminals > 0)
      .map(({ i, n }) => {
        const lead = n.points.reduce((a, b) => (b[0] < a[0] || (b[0] === a[0] && b[1] < a[1]) ? b : a));
        return { i, lead };
      })
      .sort((a, b) => a.lead[0] - b.lead[0] || a.lead[1] - b.lead[1]);
    const netNode = new Map();
    nets.forEach((n, i) => { if (n.ground) netNode.set(i, 0); });
    const labels = [];
    numbered.forEach(({ i, lead }, j) => { netNode.set(i, j + 1); labels.push({ node: j + 1, x: lead[0], y: lead[1] }); });
    const nodeAt = (p) => netNode.get(pointNet.get(key(p)));
    // Netlist node of drawing node n, phase p (0, 1, 2)
    const pn = (n, p) => (n === 0 ? 0 : phases === 3 ? 3 * (n - 1) + p + 1 : n);

    const parts = model.components.filter((c) => c.type !== 'GND');
    if (parts.length === 0) errors.push('The circuit is empty: add some components.');
    if (!model.components.some((c) => c.type === 'GND')) errors.push('No ground: add a ground symbol (node 0).');
    if (!parts.some((c) => ['V', 'V3', 'SM'].includes(c.type))) warnings.push('There is no voltage source.');

    const names = new Map();
    for (const c of parts) names.set(c.name, (names.get(c.name) || 0) + 1);
    for (const [n, k] of names) if (k > 1) warnings.push('The name ' + n + ' is used ' + k + ' times.');

    // Unconnected terminals: alone in their net
    const dangling = [];
    for (const c of parts) {
      for (const p of terminals(c)) {
        const net = nets[pointNet.get(key(p))];
        if (!net.ground && net.terminals < 2) {
          dangling.push(p);
          warnings.push(c.name + ': a terminal is not connected to anything.');
        }
      }
    }

    const lines = [];
    const componentNodes = new Map();
    for (const c of parts) {
      const T = TYPES[c.type];
      if (!T) { errors.push(c.name + ': unknown component type ' + c.type + '.'); continue; }
      if (!!T.three !== (phases === 3)) {
        errors.push(c.name + ' is a ' + (T.three ? 'three' : 'single') + '-phase component in a ' +
                    (phases === 3 ? 'three' : 'single') + '-phase drawing.');
        continue;
      }
      const ts = terminals(c);
      const a = nodeAt(ts[0]), b = ts.length > 1 ? nodeAt(ts[1]) : 0;
      componentNodes.set(c.id, [a, b]);
      if (ts.length > 1 && a === b) { errors.push(c.name + ' is short-circuited: both ends are on node ' + a + '.'); continue; }
      const P = c.params || {};
      const bad = (what) => errors.push(c.name + ': ' + what);
      const num = (k, label, optional) => {
        const v = parseValue(P[k]);
        if (v === null) { if (!optional) bad(label + ' is missing.'); return null; }
        if (Number.isNaN(v)) { bad(label + ' "' + P[k] + '" is not a number.'); return undefined; }
        return v;
      };
      const times = (k, label) => {
        const ts2 = parseList(P[k]);
        if (ts2.some((t) => Number.isNaN(t))) { bad(label + ' "' + P[k] + '" are not all numbers.'); return null; }
        return ts2;
      };
      const tag = (p) => '   # ' + c.name + (p == null ? '' : '.' + PH[p]);
      const phaseList = phases === 3 ? [0, 1, 2] : [null];

      if (['R', 'L', 'C', 'R3', 'L3', 'C3'].includes(c.type)) {
        const base = T.base || c.type;
        const v = num('value', T.params[0].label);
        if (v == null) continue;
        if (v <= 0) { bad(T.params[0].label + ' must be positive.'); continue; }
        for (const p of phaseList) lines.push(base + ' ' + pn(a, p || 0) + ' ' + pn(b, p || 0) + '  ' + fmt(v) + tag(p));
      } else if (c.type === 'V' || c.type === 'V3') {
        const mag = num('mag', 'Peak voltage'), ang = num('angle', 'Angle'), f = num('freq', 'Frequency');
        const r = num('r', 'Internal resistance', true);
        if (mag == null || ang == null || f == null || r === undefined) continue;
        const ideal = !(r > 0);
        const lk = c.type === 'V3' ? 'l1' : 'l';
        const lv = num(lk, 'Source inductance', true);
        if (lv === undefined) continue;
        if ((ideal || lv > 0) && a !== 0 && b !== 0) {
          bad('an ideal source or a source with inductance needs one terminal on ground.'); continue;
        }
        if (lv > 0 && c.type === 'V3') {   // three-phase EMF behind a coupled (sequence) impedance
          if (a !== 0) { bad('a three-phase source with impedance needs its − end on ground.'); continue; }
          const r0 = num('r0', 'R0', true), l0 = num('l0', 'L0', true);
          if (r0 === undefined || l0 === undefined) continue;
          lines.push('V3 ' + pn(b, 0) + ' ' + pn(b, 1) + ' ' + pn(b, 2) + '  ' + fmt(mag) + ' ' + fmt(ang) + ' ' + fmt(f) + '  ' +
                     fmt(r || 0) + ' ' + fmt(lv) + ' ' + fmt(r0 != null ? r0 : (r || 0)) + ' ' + fmt(l0 != null ? l0 : lv) + tag(null));
          continue;
        }
        const shift = [0, -120, 120];
        for (const p of phaseList) {
          lines.push('V ' + pn(a, p || 0) + ' ' + pn(b, p || 0) + '  ' + fmt(mag) + ' ' + fmt(ang + shift[p || 0]) + ' ' + fmt(f) +
                     (lv > 0 ? ' ' + fmt(r || 0) + ' ' + fmt(lv) : ideal ? '' : ' ' + fmt(r)) + tag(p));
        }
      } else if (c.type === 'SW' || c.type === 'SW3') {
        const indep = c.type === 'SW3' && P.mode === 'independent';
        let ok = true;
        const out = [];
        for (const p of phaseList) {
          const sk = indep ? 'state_' + PH[p] : 'state', tk = indep ? 'times_' + PH[p] : 'times';
          const tl = times(tk, (indep ? 'pole ' + PH[p] + ' ' : '') + 'switching times');
          if (!tl) { ok = false; break; }
          const state = P[sk] === 'open' ? 'open' : 'closed';
          out.push('SW ' + pn(a, p || 0) + ' ' + pn(b, p || 0) + '  ' + state + (tl.length ? ' ' + tl.map(fmt).join(' ') : '') +
                   (P.opens === 'at current zero' ? ' czero' : '') + tag(p));
        }
        if (ok) lines.push(...out);
      } else if (c.type === 'F') {
        const t0 = num('t_apply', 'Applied at'), t1 = num('t_clear', 'Cleared at', true);
        if (t0 == null || t1 === undefined) continue;
        if (t1 != null && t1 <= t0) { bad('must be cleared after it is applied.'); continue; }
        lines.push('F ' + a + ' ' + b + '  ' + fmt(t0) + (t1 != null ? ' ' + fmt(t1) : '') + tag(null));
      } else if (c.type === 'F3') {
        if (a === 0) { bad('a fault must be on a bus, not on ground.'); continue; }
        const kind = String(P.kind || 'a-g');
        const ground = kind.endsWith('-g');
        const which = kind.replace('-g', '').split('').map((ch) => PH.indexOf(ch));
        if (!which.length || which.some((p) => p < 0)) { bad('unknown fault type "' + kind + '".'); continue; }
        if (!ground && which.length < 2) { bad('a fault without ground needs at least two phases.'); continue; }
        const indep = P.mode === 'independent';
        const timing = {};
        let ok = true;
        for (const p of which) {
          const sfx = indep ? '_' + PH[p] : '';
          const lab = indep ? 'Phase ' + PH[p] + ': ' : '';
          const t0 = num('t_apply' + sfx, lab + 'applied at'), t1 = num('t_clear' + sfx, lab + 'cleared at', true);
          if (t0 == null || t1 === undefined) { ok = false; break; }
          if (t1 != null && t1 <= t0) { bad(lab + 'must be cleared after it is applied.'); ok = false; break; }
          timing[p] = fmt(t0) + (t1 != null ? ' ' + fmt(t1) : '');
        }
        if (!ok) continue;
        if (ground) {
          for (const p of which) lines.push('F ' + pn(a, p) + ' 0  ' + timing[p] + tag(p));
        } else {
          // phase-to-phase: a switch between consecutive faulted phases (ab, bc; abc -> ab + bc),
          // timed by the first phase of each pair
          for (let k = 0; k + 1 < which.length; k++) {
            const p = which[k], q = which[k + 1];
            lines.push('F ' + pn(a, p) + ' ' + pn(a, q) + '  ' + timing[p] + '   # ' + c.name + '.' + PH[p] + PH[q]);
          }
        }
      } else {
        // parameters in the order the netlist expects; optional ones may be blank (null)
        const vals = (list) => {
          const out = [];
          for (const [k, label, optional] of list) {
            const v = num(k, label, optional);
            if (v === undefined || (v === null && !optional)) return null;
            out.push(v);
          }
          return out;
        };
        const nodes3 = (n) => [0, 1, 2].map((p) => pn(n, p)).join(' ');
        const both3 = nodes3(a) + ' ' + nodes3(b);
        const or = (x, y) => (x != null ? x : y);
        const kw = (key, v) => (v != null ? ' ' + key + '=' + fmt(v) : '');
        if (c.type === 'PI') {
          const v = vals([['r', 'R'], ['l', 'L'], ['c', 'C']]);
          if (v) lines.push('PI ' + a + ' ' + b + '  ' + v.map(fmt).join(' ') + tag(null));
        } else if (c.type === 'TL') {
          const v = vals([['zc', 'Surge impedance'], ['tau', 'Travel time'], ['r', 'R', true]]);
          if (v) lines.push('TL ' + a + ' ' + b + '  ' + fmt(v[0]) + ' ' + fmt(v[1]) + ' ' + fmt(or(v[2], 0)) + tag(null));
        } else if (c.type === 'XF' || c.type === 'XF3') {
          if (a === 0 || b === 0) { bad('both transformer windings must be on a bus (not on ground).'); continue; }
          const v = vals([['S', 'Rating'], ['v1', 'Primary voltage'], ['v2', 'Secondary voltage'], ['freq', 'Frequency'],
                          ['x', 'Leakage reactance'], ['r', 'Winding resistance'], ['im', 'Magnetising current'],
                          ['knee', 'Knee', true], ['lsat', 'Saturated inductance', true]]);
          if (!v) continue;
          const head = c.type === 'XF' ? 'XF ' + a + ' 0 ' + b + ' 0  ' : 'XF3 ' + both3 + '  ' + (P.conn || 'YNd1') + ' ';
          lines.push(head + v.slice(0, 6).map(fmt).join(' ') + kw('im', v[6]) + kw('knee', v[7]) + kw('lsat', v[8]) + tag(null));
        } else if (c.type === 'MOV' || c.type === 'MOV3') {
          const v = vals([['vref', 'Reference voltage'], ['iref', 'Reference current'], ['q', 'Exponent']]);
          if (!v) continue;
          for (const p of phaseList) lines.push('MOV ' + pn(a, p || 0) + ' ' + pn(b, p || 0) + '  ' + v.map(fmt).join(' ') + tag(p));
        } else if (c.type === 'D') {
          const v = vals([['ron', 'On resistance'], ['roff', 'Off resistance'], ['vf', 'Forward voltage', true]]);
          if (v) lines.push('D ' + a + ' ' + b + ' ' + kw('ron', v[0]) + kw('roff', v[1]) + kw('vf', v[2]) + tag(null));
        } else if (c.type === 'THY') {
          const v = vals([['alpha', 'Firing angle'], ['freq', 'Frequency'], ['ref', 'Reference angle', true],
                          ['width', 'Pulse width', true], ['ron', 'On resistance'], ['roff', 'Off resistance']]);
          if (v) lines.push('THY ' + a + ' ' + b + '  ' + fmt(v[0]) + ' ' + fmt(v[1]) + kw('ref', v[2]) + kw('width', v[3]) +
                            kw('ron', v[4]) + kw('roff', v[5]) + tag(null));
        } else if (c.type === 'PI3') {
          const v = vals([['r1', 'R1'], ['l1', 'L1'], ['c1', 'C1'], ['r0', 'R0', true], ['l0', 'L0', true], ['c0', 'C0', true]]);
          if (v) lines.push('PI3 ' + both3 + '  ' + [v[0], v[1], v[2], or(v[3], v[0]), or(v[4], v[1]), or(v[5], v[2])].map(fmt).join(' ') + tag(null));
        } else if (c.type === 'RL3') {
          const v = vals([['r1', 'R1'], ['l1', 'L1'], ['r0', 'R0', true], ['l0', 'L0', true]]);
          if (v) lines.push('RL3 ' + both3 + '  ' + [v[0], v[1], or(v[2], v[0]), or(v[3], v[1])].map(fmt).join(' ') + tag(null));
        } else if (c.type === 'TL3') {
          const v = vals([['z1', 'Z1'], ['tau1', 'Travel time 1'], ['z0', 'Z0'], ['tau0', 'Travel time 0'], ['r1', 'R1', true], ['r0', 'R0', true]]);
          if (v) lines.push('TL3 ' + both3 + '  ' + [v[0], v[1], v[2], v[3], or(v[4], 0), or(v[5], or(v[4], 0))].map(fmt).join(' ') + tag(null));
        } else if (c.type === 'SM' || c.type === 'IM') {
          if (a === 0) { bad('a machine must be on a bus, not on ground.'); continue; }
          const keys = c.type === 'SM'
            ? [['S', 'Rating'], ['v', 'Voltage'], ['freq', 'Frequency'], ['H', 'H'], ['xd2', 'xd"'], ['ra', 'ra'], ['E', 'E'],
               ['delta0', 'Initial angle'], ['Pm', 'Pm'], ['d', 'Damping', true]]
            : [['S', 'Rating'], ['v', 'Voltage'], ['freq', 'Frequency'], ['poles', 'Poles'], ['rs', 'rs'], ['xls', 'xls'], ['rr', 'rr'],
               ['xlr', 'xlr'], ['xm', 'xm'], ['H', 'H'], ['Tload', 'Load torque'], ['speed0', 'Initial speed', true]];
          const v = vals(keys);
          if (!v) continue;
          const last = v.pop();
          lines.push(c.type + ' ' + nodes3(a) + '  ' + v.map(fmt).join(' ') + kw(c.type === 'SM' ? 'd' : 'speed0', last) + tag(null));
        }
      }
    }

    const junctions = [];
    for (const [k, d] of degree) if (d >= 3) junctions.push(k.split(',').map(Number));

    const N = numbered.length;
    const header = [
      '# EMTSim netlist' + (opts.title ? ': ' + opts.title : '') + ' (drawn with the EMTSim circuit editor)',
      '#',
      '# Format: R/L/C from to value | V from to peak angle freq [R] | SW from to closed|open times... | F from to t_apply [t_clear]',
      '# ' + phases * N + ' nodes' + (phases === 3 ? ' (' + N + ' three-phase nodes)' : '') + ', ' + lines.length + ' elements',
    ];
    if (phases === 3) {
      header.push('# Three-phase drawing: node k of the drawing is netlist node 3k-2 (phase a), 3k-1 (b) and 3k (c)');
    }
    header.push('');
    // run settings: time step and stop time
    const st = model.settings || {};
    const dt = parseValue(st.dt), tstop = parseValue(st.tstop);
    if (Number.isNaN(dt) || Number.isNaN(tstop)) errors.push('Time step and duration must be numbers.');
    else if (dt != null || tstop != null) {
      const d = dt != null ? dt : 100e-6, ts = tstop != null ? tstop : 0.1;
      if (!(d > 0) || !(ts > d)) errors.push('Run settings: need 0 < time step < duration.');
      else header.push('.tran ' + fmt(d) + ' ' + fmt(ts), '');
    }
    // switching interpolation and chatter removal are on unless switched off
    const off = ['chatter', 'interp'].filter((k) => st[k] === 'off');
    if (off.length) header.push('.options ' + off.map((k) => k + '=off').join(' '), '');
    const layout = '#@layout ' + JSON.stringify(serialize(model));
    const text = header.concat(lines, ['', layout]).join('\n') + '\n';
    return { text, lines, errors, warnings, phases, nodeCount: N, netlistNodes: phases * N, labels,
             componentNodes, dangling, junctions };
  }

  // ------------------------------------------------------------ files

  function serialize(model) {
    const out = {
      v: 1,
      components: model.components.map((c) => ({ type: c.type, name: c.name, x: c.x, y: c.y, rot: c.rot || 0, params: c.params || {} })),
      wires: model.wires.map((w) => ({ x1: w.x1, y1: w.y1, x2: w.x2, y2: w.y2 })),
    };
    if (model.phases === 3) out.phases = 3;
    if (model.settings && Object.values(model.settings).some((v) => v)) out.settings = Object.assign({}, model.settings);
    return out;
  }

  let nextId = 1;
  function newId() { return 'c' + (nextId++); }

  // Netlist text -> { model } if it has a drawing (#@layout line), else { raw: text }
  function parseFile(text) {
    const line = text.split(/\r?\n/).find((l) => l.startsWith('#@layout '));
    if (!line) return { raw: text };
    const data = JSON.parse(line.slice('#@layout '.length));
    return {
      model: {
        v: 1,
        phases: data.phases === 3 ? 3 : 1,
        settings: Object.assign({}, data.settings),
        components: (data.components || []).map((c) => ({ id: newId(), type: c.type, name: c.name, x: c.x, y: c.y, rot: c.rot || 0, params: Object.assign({}, c.params) })),
        wires: (data.wires || []).map((w) => ({ x1: w.x1, y1: w.y1, x2: w.x2, y2: w.y2 })),
      },
    };
  }

  function defaults(type) {
    const params = {};
    for (const p of TYPES[type].params) params[p.key] = p.def;
    return params;
  }

  function makeComponent(type, x, y, rot, existing) {
    const t = TYPES[type];
    const used = new Set((existing || []).map((c) => c.name));
    let n = 1;
    while (used.has(t.prefix + n)) n++;
    return { id: newId(), type, name: type === 'GND' ? 'GND' + n : t.prefix + n, x, y, rot: rot || 0, params: defaults(type) };
  }

  // Convert a drawing between single- and three-phase (returns a new model).
  //   1 -> 3: R, L, C, V, SW become their 3-phase versions with the same values (switch poles together).
  //           A fault F becomes a 3-phase fault F3 (type abc-g) at its first terminal.
  //   3 -> 1: the reverse; independent switch poles and fault phases use phase a's settings,
  //           and a fault F3 becomes F to a new ground symbol below it.
  function convertPhases(model, phases) {
    const from = model.phases === 3 ? 3 : 1;
    const out = { v: 1, phases, settings: Object.assign({}, model.settings), components: [],
                  wires: model.wires.map((w) => Object.assign({}, w)) };
    if (from === phases) { out.components = model.components.map((c) => Object.assign({}, c, { params: Object.assign({}, c.params) })); return out; }
    for (const c of model.components) {
      const P = c.params || {};
      if (c.type === 'GND') { out.components.push(Object.assign({}, c)); continue; }
      const type = phases === 3 ? TO3[c.type] : TO1[c.type];
      if (!type) { out.components.push(Object.assign({}, c, { params: Object.assign({}, P) })); continue; }
      const params = defaults(type);
      for (const k of Object.keys(params)) if (P[k] !== undefined) params[k] = P[k];
      const n = { id: c.id, type, name: c.name, x: c.x, y: c.y, rot: c.rot || 0, params };
      if (phases === 1 && P.mode === 'independent') {            // take phase a's settings
        if (c.type === 'SW3') { params.state = P.state_a; params.times = P.times_a; }
        if (c.type === 'F3') { params.t_apply = P.t_apply_a; params.t_clear = P.t_clear_a; }
      }
      if (type === 'F3') { params.kind = 'abc-g'; n.rot = 0; }
      if (type === 'F') {                                          // F3 (single terminal) -> F down to ground
        n.rot = 90;
        out.components.push(n);
        out.components.push({ id: newId(), type: 'GND', name: 'GND', x: c.x, y: c.y + LEN, rot: 0, params: {} });
        continue;
      }
      out.components.push(n);
    }
    return out;
  }

  return { LEN, DIRS, PH, TYPES, TO3, TO1, isThree, activeParams, singleTerminal, parseValue, parseList, fmt, formatSI,
           terminals, onSegment, connectivity, buildNetlist, serialize, parseFile, makeComponent, newId, convertPhases };
});
