// Tests for gui/schematic.js.  Run:  node gui/test_schematic.js
// With --write-example, also OVERWRITES circuits/example8.net with the original 8-node example and its drawing.
'use strict';
const fs = require('fs');
const path = require('path');
const S = require('./schematic.js');

let failures = 0;
function check(ok, what, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + what + (detail && !ok ? '\n      ' + detail : ''));
  if (!ok) failures++;
}

// Parse netlist lines into sorted, comparable element strings
function elements(text) {
  return text.split(/\r?\n/)
    .map((l) => l.split('#')[0].trim()).filter(Boolean)
    .map((l) => {
      const t = l.split(/\s+/);
      return [t[0].toUpperCase(), t[1], t[2], ...t.slice(3).map((x) => (isNaN(Number(x)) ? x : String(Number(x))))].join(' ');
    })
    .sort();
}

// ---------------------------------------------------------------- values
check(S.parseValue('3m') === 0.003, 'parseValue 3m = 0.003');
check(Math.abs(S.parseValue('30uF') - 30e-6) < 1e-18, 'parseValue 30uF = 30e-6');
check(S.parseValue('1.5k') === 1500, 'parseValue 1.5k = 1500');
check(S.parseValue('20ms') === 0.02, 'parseValue 20ms = 0.02');
check(S.parseValue('2meg') === 2e6 && S.parseValue('2M') === 2e6, 'parseValue 2meg = 2M = 2e6');
check(S.parseValue('50Hz') === 50 && S.parseValue('325 V') === 325, 'parseValue units without prefix');
check(S.parseValue('') === null && Number.isNaN(S.parseValue('abc')), 'parseValue empty -> null, junk -> NaN');
check(S.formatSI(0.003, 'H') === '3 mH' && S.formatSI(30e-6, 'F') === '30 µF', 'formatSI');

// ---------------------------------------------------------------- 8-node example drawing
function comp(type, name, x, y, rot, params) {
  return { id: S.newId(), type, name, x, y, rot, params };
}
const wire = (x1, y1, x2, y2) => ({ x1, y1, x2, y2 });
const gnd = (x, y) => comp('GND', 'GND', x, y, 0, {});

const example8 = {
  v: 1,
  components: [
    comp('V', 'VS1', 2, 12, 270, { mag: '325', angle: '0', freq: '50', r: '0.1' }), gnd(2, 12),
    comp('R', 'R12', 4, 8, 0, { value: '0.2' }),
    comp('L', 'L23', 8, 8, 0, { value: '3m' }),
    comp('R', 'RLD1', 12, 8, 90, { value: '25' }), gnd(12, 12),
    comp('C', 'C1', 15, 8, 90, { value: '30u' }), gnd(15, 12),
    comp('SW', 'SW1', 19, 8, 0, { state: 'closed', times: '55m, 80m' }),
    comp('R', 'R45', 23, 8, 0, { value: '0.3' }),
    comp('C', 'C2', 27, 8, 90, { value: '20u' }), gnd(27, 12),
    comp('L', 'L56', 31, 8, 0, { value: '4m' }),
    comp('R', 'RLD2', 35, 8, 90, { value: '30' }), gnd(35, 12),
    comp('F', 'F1', 38, 8, 90, { t_apply: '20m', t_clear: '40m' }), gnd(38, 12),
    comp('L', 'L67', 43, 8, 0, { value: '2m' }),
    comp('R', 'R78', 47, 8, 0, { value: '0.2' }),
    comp('V', 'VS2', 53, 12, 270, { mag: '325', angle: '-15', freq: '50', r: '' }), gnd(53, 12),
  ],
  wires: [wire(2, 8, 4, 8), wire(12, 8, 19, 8), wire(27, 8, 31, 8), wire(35, 8, 43, 8), wire(51, 8, 53, 8)],
};

// The built-in 8-node example (src/circuit.cpp, dataloader.py). It is compared with this fixed list,
// not with circuits/example8.net, so that editing that file in the editor never breaks the tests.
const EXAMPLE8 = `
V 0 1 325 0 50 0.1
V 0 8 325 -15 50
R 1 2 0.2
L 2 3 3e-3
R 3 0 25
C 3 0 30e-6
SW 3 4 closed 0.055 0.080
R 4 5 0.3
L 5 6 4e-3
C 5 0 20e-6
R 6 0 30
F 6 0 0.020 0.040
L 6 7 2e-3
R 7 8 0.2`;
const netPath = path.join(__dirname, '..', 'circuits', 'example8.net');
const nl = S.buildNetlist(example8, { title: 'two-source, 8-node example' });
check(nl.errors.length === 0, 'example8 drawing has no errors', nl.errors.join('; '));
check(nl.warnings.length === 0, 'example8 drawing has no warnings', nl.warnings.join('; '));
check(nl.nodeCount === 8, 'example8 drawing has 8 nodes', 'got ' + nl.nodeCount);
const want = elements(EXAMPLE8), got = elements(nl.text);
check(JSON.stringify(want) === JSON.stringify(got), 'example8 drawing gives the same elements and node numbers as the built-in example',
  'file:    ' + want.join(' | ') + '\n      drawing: ' + got.join(' | '));
check(nl.junctions.some(([x, y]) => x === 38 && y === 8), 'T-junction at the fault (38,8) is detected');

// Round trip through the #@layout line
const back = S.parseFile(nl.text);
check(back.model && back.model.components.length === example8.components.length && back.model.wires.length === 5,
  'layout survives save -> load');
check(JSON.stringify(elements(S.buildNetlist(back.model).text)) === JSON.stringify(got), 'reloaded drawing gives the same netlist');
check(S.parseFile('R 1 0 5\n').raw !== undefined, 'a netlist without a drawing loads as raw text');

// ---------------------------------------------------------------- error handling
{
  const m = { components: [comp('R', 'R1', 0, 0, 0, { value: '1' })], wires: [wire(0, 0, 4, 0)] };
  const r = S.buildNetlist(m);
  check(r.errors.some((e) => /short-circuited/.test(e)), 'short-circuited element is reported');
  check(r.errors.some((e) => /No ground/.test(e)), 'missing ground is reported');
}
{
  const m = { components: [comp('V', 'V1', 0, 0, 0, { mag: '1', angle: '0', freq: '50', r: '' }), gnd(10, 10),
                           comp('R', 'R1', 4, 0, 0, { value: 'x' })], wires: [] };
  const r = S.buildNetlist(m);
  check(r.errors.some((e) => /ideal source/.test(e)), 'ungrounded ideal source is reported');
  check(r.errors.some((e) => /not a number/.test(e)), 'invalid value is reported');
  check(r.warnings.some((w) => /not connected/.test(w)), 'unconnected terminal is reported');
}
{
  // Wire crossing without a junction must not connect
  const m = { components: [gnd(0, 4), comp('V', 'V1', 0, 4, 270, { mag: '1', angle: '0', freq: '50', r: '1' }),
                           comp('R', 'R1', 2, 0, 90, { value: '1' }), gnd(2, 4)],
              wires: [wire(-2, 2, 4, 2)] };   // horizontal wire crossing R1's body and V1's body
  const r = S.buildNetlist(m);
  check(r.nodeCount === 2, 'wires crossing element bodies do not connect', 'nodes: ' + r.nodeCount);
}

// ---------------------------------------------------------------- three-phase
{
  // Source (Norton) 0 -> bus 1, line R3 1 -> 2, shunt C3 2 -> 0
  const m3 = { phases: 3, components: [
    comp('V3', 'G', 0, 4, 270, { mag: '325', angle: '10', freq: '50', r: '0.1' }), gnd(0, 4),
    comp('R3', 'RL', 0, 0, 0, { value: '2' }),
    comp('C3', 'CS', 4, 0, 90, { value: '10u' }), gnd(4, 4)], wires: [] };
  const r = S.buildNetlist(m3);
  check(r.errors.length === 0 && r.nodeCount === 2 && r.netlistNodes === 6, '3-phase: 2 drawing nodes become 6 netlist nodes',
        r.errors.join('; ') + ' nodes ' + r.nodeCount + '/' + r.netlistNodes);
  const L = r.lines.map((l) => l.split('#')[0].trim());
  check(JSON.stringify(L) === JSON.stringify([
    'V 0 1  325 10 50 0.1', 'V 0 2  325 -110 50 0.1', 'V 0 3  325 130 50 0.1',
    'R 1 4  2', 'R 2 5  2', 'R 3 6  2',
    'C 4 0  0.00001', 'C 5 0  0.00001', 'C 6 0  0.00001']),
    '3-phase: source phases a/b/c at +0/-120/+120 deg, R and C per phase on nodes 3k-2..3k', JSON.stringify(L));
  check(/\.b\s*$/.test(r.lines[1]) && /# 6 nodes \(2 three-phase nodes\)/.test(r.text), '3-phase: names end in .a/.b/.c, header counts phases');

  const sw = (params) => S.buildNetlist({ phases: 3, components: [comp('SW3', 'S', 0, 0, 0, params),
    comp('R3', 'R', 4, 0, 90, { value: '1' }), gnd(4, 4), comp('R3', 'Rs', 0, 0, 90, { value: '1' }), gnd(0, 4)], wires: [] })
    .lines.filter((l) => l.startsWith('SW')).map((l) => l.split('#')[0].trim());
  check(JSON.stringify(sw({ mode: 'together', state: 'closed', times: '30m 80m' })) ===
        JSON.stringify(['SW 1 4  closed 0.03 0.08', 'SW 2 5  closed 0.03 0.08', 'SW 3 6  closed 0.03 0.08']),
        '3-phase switch, poles together');
  check(JSON.stringify(sw({ mode: 'independent', state_a: 'closed', times_a: '60m', state_b: 'open', times_b: '', state_c: 'closed', times_c: '66.7m' })) ===
        JSON.stringify(['SW 1 4  closed 0.06', 'SW 2 5  open', 'SW 3 6  closed 0.0667']),
        '3-phase switch, poles independent', JSON.stringify(sw({ mode: 'independent', state_a: 'closed', times_a: '60m', state_b: 'open', times_b: '', state_c: 'closed', times_c: '66.7m' })));

  const flt = (params) => {
    const res = S.buildNetlist({ phases: 3, components: [comp('R3', 'R', 0, 0, 90, { value: '1' }), gnd(0, 4),
      comp('F3', 'F', 0, 0, 0, Object.assign({ mode: 'together', t_apply: '20m', t_clear: '40m' }, params))], wires: [] });
    return { lines: res.lines.filter((l) => l.startsWith('F')).map((l) => l.split('#')[0].trim()), errors: res.errors };
  };
  const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  check(eq(flt({ kind: 'b-g' }).lines, ['F 2 0  0.02 0.04']), '3-phase fault b-g: phase b to ground');
  check(eq(flt({ kind: 'ca' }).lines, ['F 3 1  0.02 0.04']), '3-phase fault ca: between phases c and a');
  check(eq(flt({ kind: 'abc' }).lines, ['F 1 2  0.02 0.04', 'F 2 3  0.02 0.04']), '3-phase fault abc (no ground): a-b and b-c');
  check(eq(flt({ kind: 'abc-g' }).lines, ['F 1 0  0.02 0.04', 'F 2 0  0.02 0.04', 'F 3 0  0.02 0.04']), '3-phase fault abc-g: every phase to ground');
  check(eq(flt({ kind: 'ab-g', mode: 'independent', t_apply_a: '20m', t_clear_a: '', t_apply_b: '25m', t_clear_b: '45m' }).lines,
           ['F 1 0  0.02', 'F 2 0  0.025 0.045']), '3-phase fault ab-g with independent timing (a permanent)');
  check(flt({ kind: 'a-g', t_apply: '40m', t_clear: '30m' }).errors.some((e) => /cleared after/.test(e)), '3-phase fault: clearing before applying is reported');

  const mixed = S.buildNetlist({ phases: 3, components: [comp('R', 'R1', 0, 0, 90, { value: '1' }), gnd(0, 4)], wires: [] });
  check(mixed.errors.some((e) => /single-phase component in a three-phase drawing/.test(e)), 'single-phase part in a 3-phase drawing is reported');

  // Converting the 8-node example to three-phase and back
  const to3 = S.convertPhases(example8, 3);
  const n3 = S.buildNetlist(to3);
  check(n3.errors.length === 0 && n3.nodeCount === 8 && n3.netlistNodes === 24 && n3.lines.length === 14 * 3,
        'example8 converted to 3-phase: 8 x 3 nodes, every element x 3', n3.errors.join('; ') + ' ' + n3.nodeCount + ' ' + n3.lines.length);
  const back = S.buildNetlist(S.convertPhases(to3, 1));
  check(back.errors.length === 0 && eq(elements(back.text), elements(EXAMPLE8)), 'converting back to single-phase restores the netlist',
        back.errors.join('; ') + ' | ' + elements(back.text).join(' | '));
  const re = S.parseFile(n3.text);
  check(re.model.phases === 3 && eq(S.buildNetlist(re.model).lines, n3.lines), '3-phase drawing survives save -> load');
}

// ---------------------------------------------------------------- new components
{
  const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const lines = (m) => { const r = S.buildNetlist(m); return { L: r.lines.map((l) => l.split('#')[0].trim()), r }; };
  // single-phase: source with inductance, pi line, Bergeron line, transformer, arrester, diode, thyristor
  const m1 = { components: [
    comp('V', 'G', 0, 4, 270, { mag: '100', angle: '0', freq: '50', r: '0.1', l: '1m' }), gnd(0, 4),
    comp('PI', 'LN', 0, 0, 0, { r: '1', l: '10m', c: '1u' }),
    comp('TL', 'TL', 4, 0, 0, { zc: '400', tau: '1m', r: '' }),
    comp('XF', 'T', 8, 0, 0, { S: '1M', v1: '11k', v2: '400', freq: '50', x: '0.06', r: '0.01', im: '1', knee: '1.15', lsat: '' }),
    comp('MOV', 'A', 12, 0, 90, { vref: '600', iref: '1k', q: '26' }), gnd(12, 4),
    comp('D', 'D', 12, 0, 0, { ron: '1m', roff: '1meg', vf: '' }),
    comp('THY', 'TH', 16, 0, 0, { alpha: '30', freq: '50', ref: '60', width: '120', ron: '1m', roff: '1meg' }),
    comp('R', 'RL', 20, 0, 90, { value: '10' }), gnd(20, 4)], wires: [], settings: { dt: '50u', tstop: '40m' } };
  const a = lines(m1);
  check(a.r.errors.length === 0, 'new single-phase components: no errors', a.r.errors.join('; '));
  check(eq(a.L, ['V 0 1  100 0 50 0.1 0.001', 'PI 1 2  1 0.01 0.000001', 'TL 2 3  400 0.001 0', 'XF 3 0 4 0  1000000 11000 400 50 0.06 0.01 im=1 knee=1.15',
                 'MOV 4 0  600 1000 26', 'D 4 5  ron=0.001 roff=1000000', 'THY 5 6  30 50 ref=60 width=120 ron=0.001 roff=1000000', 'R 6 0  10']),
        'new single-phase components write the expected netlist lines', JSON.stringify(a.L));
  check(/^\.tran 0\.00005 0\.04$/m.test(a.r.text), 'run settings are written as a .tran line');
  check(!/^\.options/m.test(a.r.text), 'no .options line while chatter removal and interpolation are on (the default)');
  {
    const m2 = Object.assign({}, m1, { settings: { dt: '50u', tstop: '40m', chatter: 'off', interp: 'off' } });
    const t2 = S.buildNetlist(m2).text;
    check(/^\.options chatter=off interp=off$/m.test(t2), 'switched-off options are written as a .options line');
    const back = S.parseFile('#@layout ' + JSON.stringify(S.serialize(m2))).model;
    check(back.settings.chatter === 'off' && back.settings.interp === 'off', 'the options survive save and load');
  }
  // three-phase: source with sequence impedance, pi line, coupled RL, Bergeron line, transformer, arresters, machines
  const m3 = { phases: 3, components: [
    comp('V3', 'GRID', 0, 4, 270, { mag: '8981.6', angle: '0', freq: '50', r: '0.02', l1: '2m', r0: '', l0: '5m' }), gnd(0, 4),
    comp('PI3', 'LN', 0, 0, 0, { r1: '1', l1: '10m', c1: '1u', r0: '3', l0: '', c0: '' }),
    comp('RL3', 'Z', 4, 0, 0, { r1: '0.5', l1: '5m', r0: '', l0: '' }),
    comp('TL3', 'TL', 8, 0, 0, { z1: '300', tau1: '1m', z0: '600', tau0: '1.3m', r1: '1', r0: '' }),
    comp('XF3', 'T', 12, 0, 0, { conn: 'Dyn11', S: '2M', v1: '11k', v2: '400', freq: '50', x: '0.06', r: '0.01', im: '1', knee: '', lsat: '' }),
    comp('MOV3', 'A', 16, 0, 90, { vref: '600', iref: '1k', q: '26' }), gnd(16, 4),
    comp('SW3', 'BRK', 16, 0, 0, { mode: 'together', state: 'closed', times: '50m', opens: 'at current zero' }),
    comp('IM', 'M', 20, 0, 0, { S: '100k', v: '400', freq: '50', poles: '4', rs: '0.01', xls: '0.1', rr: '0.04', xlr: '0.1', xm: '3', H: '0.3', Tload: '0.5', speed0: '' }),
    comp('SM', 'G', 4, 0, 0, { S: '2M', v: '11k', freq: '50', H: '3', xd2: '0.2', ra: '0.003', E: '1.1', delta0: '20', Pm: '0.5', d: '2' })],
    wires: [wire(20, 0, 22, 0)] };
  const b3 = lines(m3);
  check(b3.r.errors.length === 0, 'new three-phase components: no errors', b3.r.errors.join('; '));
  const want3 = ['V3 1 2 3  8981.6 0 50  0.02 0.002 0.02 0.005', 'PI3 1 2 3 4 5 6  1 0.01 0.000001 3 0.01 0.000001',
                 'RL3 4 5 6 7 8 9  0.5 0.005 0.5 0.005', 'TL3 7 8 9 10 11 12  300 0.001 600 0.0013 1 1',
                 'XF3 10 11 12 13 14 15  Dyn11 2000000 11000 400 50 0.06 0.01 im=1',
                 'MOV 13 0  600 1000 26', 'MOV 14 0  600 1000 26', 'MOV 15 0  600 1000 26',
                 'SW 13 16  closed 0.05 czero', 'SW 14 17  closed 0.05 czero', 'SW 15 18  closed 0.05 czero',
                 'IM 16 17 18  100000 400 50 4 0.01 0.1 0.04 0.1 3 0.3 0.5',
                 'SM 4 5 6  2000000 11000 50 3 0.2 0.003 1.1 20 0.5 d=2'];
  check(eq(b3.L, want3), 'new three-phase components write the expected netlist lines', JSON.stringify(b3.L));
  // the C++ simulator accepts both netlists
  const exe = path.join(__dirname, '..', 'build', 'emtsim.exe');
  if (fs.existsSync(exe)) {
    const os = require('os'), { execFileSync } = require('child_process');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'emtsim-'));
    for (const [nm, text] of [['single', a.r.text], ['three', b3.r.text]]) {
      fs.writeFileSync(path.join(dir, nm + '.net'), text);
      let ok = true, out = '';
      try { out = execFileSync(exe, [path.join(dir, nm + '.net')], { cwd: dir, encoding: 'utf8' }); } catch (e) { ok = false; out = String(e.stderr || e); }
      check(ok && /Done:/.test(out), 'the C++ simulator runs the ' + nm + '-phase netlist written by the editor', out.slice(-300));
    }
    fs.rmSync(dir, { recursive: true, force: true });
  }
  // mode conversion maps the new two-terminal parts
  const c3 = S.convertPhases({ components: [comp('PI', 'LN', 0, 0, 0, { r: '1', l: '10m', c: '1u' })], wires: [] }, 3);
  check(c3.components[0].type === 'PI3', 'converting to three-phase turns a PI line into a PI3 line');
}

if (process.argv.includes('--write-example')) {
  fs.writeFileSync(netPath, nl.text);
  console.log('Overwrote ' + netPath + ' with the original 8-node example and its drawing');
}

console.log(failures ? '\n' + failures + ' FAILED' : '\nAll tests passed');
process.exit(failures ? 1 : 0);
