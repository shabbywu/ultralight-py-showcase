const { buildSync } = require("esbuild");
const assert = require("node:assert/strict");
const path = require("node:path");
const os = require("node:os");
const fs = require("node:fs");
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "inventory-session-"));
const output = path.join(dir, "session.cjs");
buildSync({
  entryPoints: [path.resolve(__dirname, "../src/session.js")],
  outfile: output,
  bundle: true,
  platform: "node",
  format: "cjs",
});
global.window = {};
let records = new Map();
global.localStorage = {
  getItem: (k) => records.get(k) || null,
  setItem: (k, v) => records.set(k, v),
};
let session = require(output);
assert.equal(session.engine.snapshot().items.length, 20);
const old = {
  __godot_bag: [
    {
      id: "kept",
      x: 2,
      y: 3,
      w: 4,
      h: 1,
      quantity: 1,
      rotateDeg: 90,
      content: '<img src="./reliquary/items/pilgrims-oath.webp">',
    },
  ],
};
const migrated = session.migrate(old);
assert.equal(migrated.items[0].id, "kept");
assert.deepEqual(migrated.items[0].position, {
  container: "bag",
  x: 2,
  y: 3,
  rotation: 1,
});
assert(!JSON.stringify(migrated).includes("content"));
assert.throws(
  () => session.migrate({ __godot_bag: [{ id: "bad", content: "unknown" }] }),
  /Unknown legacy artwork for bad/
);
assert(session.save());
const snapshot = records.get("ashen-reliquary:snapshot:v1");
assert(snapshot);
delete require.cache[require.resolve(output)];
session = require(output);
assert.equal(JSON.stringify(session.engine.snapshot()), snapshot);
const normalWriter = global.localStorage.setItem;
global.localStorage.setItem = () => {
  throw Error("Storage quota exceeded");
};
const beforeFailure = session.engine.snapshot();
assert.equal(session.save(), false);
assert.match(session.persistenceError, /Storage quota exceeded/);
assert.deepEqual(session.engine.snapshot(), beforeFailure);
global.localStorage.setItem = normalWriter;
assert(session.save());
assert.equal(session.persistenceError, "");
records = new Map([
  [
    "ashen-reliquary:__godot_bag",
    JSON.stringify([{ id: "bad", content: "unknown" }]),
  ],
]);
delete require.cache[require.resolve(output)];
session = require(output);
assert.match(session.persistenceError, /Load blocked.*bad/);
assert.equal(session.save(), false);
assert(!records.has("ashen-reliquary:snapshot:v1"));
assert(records.has("ashen-reliquary:__godot_bag"));
fs.rmSync(dir, { recursive: true });
console.log("Session migration, reload, and failed migration protection: PASS");
