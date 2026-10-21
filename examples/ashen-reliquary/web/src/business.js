import { engine, definitions } from "./session";
// Demonstration game rules. The inventory package knows nothing about these numbers.
export function attributes(state = engine.snapshot()) {
  const equipped = state.items.filter(
    (i) =>
      state.containers.find((c) => c.id === i.position.container)?.kind ===
      "slot"
  );
  const socketed = state.items.filter((i) => {
    const c = state.containers.find((c) => c.id === i.position.container);
    return c?.kind === "socket" && equipped.some((e) => e.id === c.owner);
  });
  return {
    power:
      10 +
      equipped.reduce(
        (n, i) => n + definitions.findIndex((d) => d.id === i.definition) + 2,
        0
      ) +
      socketed.length * 5,
    ward: 5 + equipped.length * 3,
  };
}
export function comparison(id) {
  const state = engine.snapshot(),
    item = state.items.find((i) => i.id === id);
  if (!item) return "";
  const d = definitions.find((d) => d.id === item.definition),
    slot = state.containers.find(
      (c) => c.kind === "slot" && d.slots.includes(c.slot)
    );
  if (!slot) return "";
  const preview = engine.preview({ type: "equip", id, slot: slot.id });
  if (!preview.ok) return preview.message;
  const before = attributes(state),
    after = attributes(preview.snapshot);
  return `Equip: Power ${after.power - before.power >= 0 ? "+" : ""}${
    after.power - before.power
  } · Ward ${after.ward - before.ward >= 0 ? "+" : ""}${
    after.ward - before.ward
  }`;
}
