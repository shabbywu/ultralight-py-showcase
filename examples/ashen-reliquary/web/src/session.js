import { Inventory } from "grid-inventory/core";
import { items } from "./items";
export const definitions = items.map((i, n) => ({
  ...i,
  id: i.key,
  width: i.w,
  height: i.h,
  rotatable: true,
  maxStack: i.key === "ember-flask" ? 20 : 1,
  slots:
    n === 0
      ? ["mainhand"]
      : n === 2
      ? ["head"]
      : n === 3
      ? ["gloves"]
      : n === 4
      ? ["offhand"]
      : [1, 5, 6, 16].includes(n)
      ? ["mainhand"]
      : n === 12
      ? ["ring"]
      : n === 10
      ? ["neck"]
      : [],
  twoHanded: n === 0,
}));
definitions.push(
  {
    id: "gothic-breastplate",
    name: "Ashen Breastplate",
    rarity: "rare",
    width: 2,
    height: 3,
    rotatable: true,
    maxStack: 1,
    slots: ["chest"],
  },
  {
    id: "double-cross",
    name: "Ember Gem",
    rarity: "relic",
    width: 1,
    height: 1,
    maxStack: 20,
    slots: [],
  }
);
export const engine = new Inventory(definitions, [
  { id: "ground", kind: "grid", width: 12, height: 12 },
  { id: "bag", kind: "grid", width: 12, height: 6 },
  ...[
    "head",
    "chest",
    "gloves",
    "neck",
    "ring1",
    "ring2",
    "mainhand",
    "offhand",
  ].map((slot) => ({
    id: slot,
    kind: "slot",
    slot: slot.startsWith("ring") ? "ring" : slot,
  })),
]);
export const hostName = window.inventory ? "Python / Ultralight" : "Browser";
const key = "ashen-reliquary:snapshot:v1";
export let persistenceError = "";
export function save() {
  if (persistenceError.startsWith("Load blocked:")) return false;
  try {
    const encoded = JSON.stringify(engine.snapshot());
    if (window.inventory) window.inventory.save_snapshot(encoded);
    else localStorage.setItem(key, encoded);
    persistenceError = "";
    return true;
  } catch (e) {
    persistenceError = String(e);
    return false;
  }
}
export function addRelic() {
  const d = definitions[Math.floor(Math.random() * definitions.length)];
  const id = "relic-" + Date.now() + "-" + Math.random().toString(36).slice(2);
  for (let y = 0; y < 12; y++)
    for (let x = 0; x < 12; x++)
      if (
        engine.execute({
          type: "add",
          item: {
            id,
            definition: d.id,
            quantity: 1,
            position: { container: "ground", x, y },
          },
        }).ok
      )
        return true;
  return false;
}
export function migrate(layouts) {
  const state = engine.snapshot();
  state.items = [];
  state.shortcuts = {};
  state.revision = 0;
  state.containers = state.containers.filter((c) => c.kind !== "socket");
  for (const [name, records] of Object.entries(layouts)) {
    if (!["__godot_ground", "__godot_bag"].includes(name))
      throw Error("Unknown legacy container: " + name);
    if (!Array.isArray(records))
      throw Error("Invalid legacy inventory: " + name);
    for (const old of records) {
      const match = String(old.content).match(
          /reliquary\/items\/([a-z-]+)\.webp/
        ),
        definition = definitions.find((d) => d.id === match?.[1]);
      if (!definition) throw Error("Unknown legacy artwork for " + old.id);
      state.items.push({
        id: old.id,
        definition: definition.id,
        quantity: old.quantity ?? 1,
        position: {
          container: name === "__godot_ground" ? "ground" : "bag",
          x: old.x,
          y: old.y,
          rotation:
            old.rotation ??
            (old.rotateDeg !== undefined
              ? old.rotateDeg / 90
              : old.w === definition.height &&
                old.h === definition.width &&
                definition.width !== definition.height
              ? 1
              : 0),
        },
      });
    }
  }
  return state;
}
try {
  const encoded = window.inventory
    ? window.inventory.load_snapshot()
    : localStorage.getItem(key);
  if (encoded && encoded !== "null") {
    const result = engine.load(JSON.parse(encoded));
    if (!result.ok) throw Error(result.message);
  } else {
    const legacy = {};
    for (const name of ["__godot_ground", "__godot_bag"]) {
      const raw = window.inventory
        ? window.inventory.load_layout(name)
        : localStorage.getItem("ashen-reliquary:" + name);
      if (raw && raw !== "null") legacy[name] = JSON.parse(raw);
    }
    if (Object.keys(legacy).length) {
      const result = engine.load(migrate(legacy));
      if (!result.ok) throw Error(result.message);
    } else {
      definitions.slice(0, 18).forEach((d, n) =>
        engine.execute({
          type: "add",
          item: {
            id: "seed-" + n,
            definition: d.id,
            quantity: d.maxStack > 1 ? 8 : 1,
            position: {
              container: n < 10 ? "ground" : "bag",
              x: (n % 4) * 3,
              y: Math.floor((n < 10 ? n : n - 10) / 4) * 4,
            },
          },
        })
      );
      for (const [id, definition, x, y, quantity] of [
        ["chest", "gothic-breastplate", 0, 1, 1],
        ["gem", "double-cross", 11, 0, 6],
      ])
        engine.execute({
          type: "add",
          item: {
            id,
            definition,
            quantity,
            position: { container: "bag", x, y },
          },
        });
    }
    const seeded = engine.snapshot();
    if (seeded.items.some((i) => i.id === "seed-0")) {
      seeded.containers.push({
        id: "saint-socket",
        kind: "socket",
        owner: "seed-0",
        accepts: ["double-cross"],
      });
      engine.load(seeded);
    }
  }
} catch (e) {
  persistenceError = "Load blocked: " + String(e);
}
engine.on("change", () => {
  if (!persistenceError.startsWith("Load blocked:")) save();
});
engine.on("activate", ({ itemId, kind }) => {
  if (kind === "shortcut") return;
  const item = engine.snapshot().items.find((i) => i.id === itemId);
  if (!item) return;
  const d = engine.definitions.get(item.definition);
  if (
    kind === "transfer" ||
    !["ground", "bag"].includes(item.position.container)
  ) {
    const to = engine.findSpace(
      itemId,
      item.position.container === "ground"
        ? "bag"
        : item.position.container === "bag"
        ? "ground"
        : "bag"
    );
    if (to) engine.execute({ type: "move", id: itemId, to });
  } else {
    const slots = engine
      .snapshot()
      .containers.filter((c) => c.kind === "slot" && d.slots.includes(c.slot));
    slots.sort(
      (a, b) =>
        Number(
          engine.snapshot().items.some((i) => i.position.container === a.id)
        ) -
        Number(
          engine.snapshot().items.some((i) => i.position.container === b.id)
        )
    );
    for (const slot of slots) if (engine.equip(itemId, slot.id).ok) break;
  }
});
export function activate(key) {
  const reference = engine.snapshot().shortcuts[key];
  engine.emit("activate", { ...reference, kind: "shortcut" });
  if (reference?.item) {
    const item = engine.snapshot().items.find((i) => i.id === reference.item);
    if (item?.definition === "ember-flask")
      engine.execute({ type: "consume", id: item.id, quantity: 1 });
  }
}
window.Reliquary = {
  snapshot: () => engine.snapshot(),
  engine,
  addRelic,
  save,
  host: hostName,
};
