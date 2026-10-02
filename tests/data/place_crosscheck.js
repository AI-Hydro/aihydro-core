// Independent re-derivation of aihydro.geom/1 ids and basin anchor ids from the raw
// inputs in place_vectors.json. Node only, no dependencies.
// Run: node tests/data/place_crosscheck.js
const fs = require("fs");
const crypto = require("crypto");
const path = require("path");
const vec = JSON.parse(fs.readFileSync(path.join(__dirname, "place_vectors.json"), "utf8"));

// RFC 8785 JCS for the subset used here: objects, arrays, strings, safe integers.
function jcs(v) {
  if (v === null || typeof v === "boolean") return JSON.stringify(v);
  if (typeof v === "number") { if (!Number.isSafeInteger(v)) throw new Error("non-integer " + v); return String(v); }
  if (typeof v === "string") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(jcs).join(",") + "]";
  const keys = Object.keys(v).sort(); // UTF-16 code unit order (default sort); keys are ASCII
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + jcs(v[k])).join(",") + "}";
}
const digest = (o) => "sha256:" + crypto.createHash("sha256").update(Buffer.from(jcs(o), "utf8")).digest("hex");

function roundHalfEven(x) {
  const f = Math.floor(x), d = x - f;
  if (d < 0.5) return f;
  if (d > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}
const q = (v) => { const r = roundHalfEven(v * 1e6); return r === 0 ? 0 : r; };
const qpos = (p) => [q(p[0]), q(p[1])];
const cmp = (a, b) => { // lexicographic compare of nested int arrays
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const c = Array.isArray(a[i]) ? cmp(a[i], b[i]) : a[i] - b[i];
    if (c !== 0) return c;
  }
  return a.length - b.length;
};
const area2 = (r) => { let t = 0n; for (let i = 0; i < r.length; i++) { const [x1, y1] = r[i], [x2, y2] = r[(i + 1) % r.length]; t += BigInt(x1) * BigInt(y2) - BigInt(x2) * BigInt(y1); } return t; };
function clean(raw) {
  let pts = [];
  for (const p of raw) { const c = qpos(p); if (!pts.length || pts[pts.length - 1][0] !== c[0] || pts[pts.length - 1][1] !== c[1]) pts.push(c); }
  while (pts.length > 1 && pts[pts.length - 1][0] === pts[0][0] && pts[pts.length - 1][1] === pts[0][1]) pts.pop();
  return pts.length < 3 || area2(pts) === 0n ? null : pts;
}
function orient(r, ccw) {
  if ((area2(r) > 0n) !== ccw) r = r.slice().reverse();
  let s = 0; for (let i = 1; i < r.length; i++) if (cmp(r[i], r[s]) < 0) s = i;
  return r.slice(s).concat(r.slice(0, s));
}
function geomPayload(g) {
  const base = { alg: "aihydro.geom/1", q_exp: 6 };
  if (g.type === "GaugeID") return { ...base, type: "GaugeID", scheme: g.scheme, id: g.id };
  if (g.type === "Point") return { ...base, type: "Point", coordinates: qpos(g.coordinates) };
  if (g.type === "MultiPoint") {
    const pts = g.coordinates.map(qpos).sort(cmp).filter((p, i, a) => i === 0 || cmp(p, a[i - 1]) !== 0);
    return { ...base, type: "MultiPoint", coordinates: pts };
  }
  const polys = (g.type === "Polygon" ? [g.coordinates] : g.coordinates).map((rings) => {
    const ext = clean(rings[0]); if (!ext) return null;
    const holes = rings.slice(1).map(clean).filter(Boolean).map((h) => orient(h, false)).sort(cmp);
    return [orient(ext, true)].concat(holes);
  }).filter(Boolean).sort(cmp);
  return { ...base, type: "MultiPolygon", coordinates: polys };
}

let ok = true;
for (const c of vec.geometry) {
  const payload = geomPayload(c.input), d = digest(payload);
  const same = jcs(payload) === jcs(c.payload) && d === c.digest;
  ok = ok && same; console.log((same ? "OK   " : "FAIL ") + "geometry " + c.name + " " + d);
}
for (const c of vec.anchors) {
  const id = "aihydro:basin:" + digest({ schema: "aihydro.basin_anchor/1", ...c.anchor });
  const same = id === c.id; ok = ok && same;
  console.log((same ? "OK   " : "FAIL ") + "anchor   " + c.name + " " + id);
}
process.exit(ok ? 0 : 1);
