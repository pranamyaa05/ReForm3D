import * as THREE from "three";

const TAU = Math.PI * 2;

function hash(n) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

function outline({ broken, teeth, rRoot, rTip }) {
  const per = 14;
  const total = teeth * per;
  const pts = [];
  for (let i = 0; i < total; i++) {
    const a = (i / total) * TAU;
    const f = (a * teeth) / TAU;
    const frac = f - Math.floor(f);
    let r;
    if (frac < 0.29) r = rRoot;
    else if (frac < 0.4) r = rRoot + (rTip - rRoot) * ((frac - 0.29) / 0.11);
    else if (frac < 0.65) r = rTip;
    else if (frac < 0.76) r = rTip - (rTip - rRoot) * ((frac - 0.65) / 0.11);
    else r = rRoot;

    if (broken) {
      const width = 0.47;
      const distance = Math.abs(Math.atan2(Math.sin(a), Math.cos(a)));
      if (distance < width) {
        const t = distance / width;
        const dip = Math.pow(Math.cos((t * Math.PI) / 2), 1.35);
        const jagged = 0.58 + 0.82 * hash(i);
        r *= 1 - dip * jagged * 0.46;
      }
    }
    pts.push(new THREE.Vector2(Math.cos(a) * r, Math.sin(a) * r));
  }
  return pts;
}

export function buildGearGeometry({
  broken = false,
  teeth = 20,
  rootRadius = 0.82,
  tipRadius = 1.08,
  boreRadius = 0.17,
  boltRadius = 0.58,
  boltHoleRadius = 0.105,
} = {}) {
  const shape = new THREE.Shape(outline({
    broken,
    teeth,
    rRoot: rootRadius,
    rTip: tipRadius,
  }));

  const bore = new THREE.Path();
  bore.absarc(0, 0, boreRadius, 0, TAU, true);
  shape.holes.push(bore);

  for (let k = 0; k < 4; k++) {
    const a = (k * TAU) / 4 + TAU / 8;
    const hole = new THREE.Path();
    hole.absarc(Math.cos(a) * boltRadius, Math.sin(a) * boltRadius, boltHoleRadius, 0, TAU, true);
    shape.holes.push(hole);
  }

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: 0.68,
    bevelEnabled: true,
    bevelThickness: 0.055,
    bevelSize: 0.028,
    bevelSegments: 4,
    curveSegments: 28,
  });
  geometry.center();
  geometry.computeVertexNormals();
  return geometry;
}
