"""Typed application methods and detached wire encoding for Ultralight."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reliquary.codec import (
    WireObject,
    encode_comparison,
    encode_definition,
    encode_event,
    encode_read_model,
    encode_result,
)
from reliquary.game import Game
from reliquary.models import StateEvent

if TYPE_CHECKING:
    from ultralight_py import View


class GameBridge:
    """Expose explicit application methods; never accept generic commands or snapshots."""

    MEMBERS = (
        "read",
        "definitions",
        "create_relic",
        "save",
        "comparison",
        "host_name",
        "move_item",
        "preview_move_item",
        "remove_item",
        "preview_remove_item",
        "split_stack",
        "preview_split_stack",
        "merge_stacks",
        "preview_merge_stacks",
        "equip_item",
        "preview_equip_item",
        "equip_best_slot",
        "preview_equip_best_slot",
        "transfer_item",
        "preview_transfer_item",
        "socket_gem",
        "preview_socket_gem",
        "unsocket_gem",
        "preview_unsocket_gem",
        "bind_item",
        "preview_bind_item",
        "activate_shortcut",
        "preview_activate_shortcut",
    )

    def __init__(self, game: Game) -> None:
        """Retain one typed game and an optional View notification subscription."""
        self._game = game
        self._token: int | None = None

    def host_name(self) -> str:
        """Return the native host display name."""
        return "Python / Ultralight"

    @property
    def definitions(self) -> list[WireObject]:
        """Encode immutable backend definitions into independent transport records."""
        return [encode_definition(d) for d in self._game.definitions]

    def read(self) -> WireObject:
        """Encode an independent render projection at the bridge boundary."""
        return encode_read_model(self._game.read())

    def create_relic(self) -> WireObject:
        """Request backend generation without accepting client item data."""
        return encode_result(self._game.create_relic())

    def save(self) -> bool:
        """Retry persistence of the current authoritative state."""
        return self._game.save()

    def comparison(self, item_id: str) -> WireObject | None:
        """Return an encoded equipment delta or rejection explanation."""
        return encode_comparison(self._game.comparison(item_id))

    def connect(self, view: View) -> None:
        """Attach a single backend event channel to a View."""
        self.close()

        def notify(event: StateEvent) -> None:
            """Deliver an encoded event through a scoped JavaScript handle."""
            if view.closed or not view.is_ready:
                return
            with view.evaluate_handle(
                "event => window.dispatchEvent(new CustomEvent('inventory-changed', "
                "{detail: Python.to_value(event)}))"
            ) as callback:
                callback.call(encode_event(event))

        self._token = self._game.subscribe(notify)

    def close(self) -> None:
        """Release the host event subscription when its View is closed."""
        if self._token is not None:
            self._game.unsubscribe(self._token)
            self._token = None

    def move_item(
        self,
        item_id: str,
        container_id: str,
        x: int,
        y: int,
        rotation: int,
        expected_revision: int | None = None,
    ) -> WireObject:
        """Move an item to an exact grid position."""
        return encode_result(
            self._game.move_item(
                item_id, container_id, x, y, rotation, expected_revision
            )
        )

    def preview_move_item(
        self, item_id: str, container_id: str, x: int, y: int, rotation: int
    ) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(
            self._game.preview_move_item(item_id, container_id, x, y, rotation)
        )

    def remove_item(
        self, item_id: str, expected_revision: int | None = None
    ) -> WireObject:
        """Delete an item and its dependent sockets."""
        return encode_result(self._game.remove_item(item_id, expected_revision))

    def preview_remove_item(self, item_id: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_remove_item(item_id))

    def split_stack(
        self,
        item_id: str,
        quantity: int,
        container_id: str,
        x: int,
        y: int,
        rotation: int,
        expected_revision: int | None = None,
    ) -> WireObject:
        """Split a stack using a backend-generated identity."""
        return encode_result(
            self._game.split_stack(
                item_id, quantity, container_id, x, y, rotation, expected_revision
            )
        )

    def preview_split_stack(
        self,
        item_id: str,
        quantity: int,
        container_id: str,
        x: int,
        y: int,
        rotation: int,
    ) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(
            self._game.preview_split_stack(
                item_id, quantity, container_id, x, y, rotation
            )
        )

    def merge_stacks(
        self, item_id: str, target_id: str, expected_revision: int | None = None
    ) -> WireObject:
        """Merge compatible item stacks."""
        return encode_result(
            self._game.merge_stacks(item_id, target_id, expected_revision)
        )

    def preview_merge_stacks(self, item_id: str, target_id: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_merge_stacks(item_id, target_id))

    def equip_item(
        self, item_id: str, slot_id: str, expected_revision: int | None = None
    ) -> WireObject:
        """Equip an item and return conflicting equipment."""
        return encode_result(self._game.equip_item(item_id, slot_id, expected_revision))

    def preview_equip_item(self, item_id: str, slot_id: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_equip_item(item_id, slot_id))

    def equip_best_slot(
        self, item_id: str, expected_revision: int | None = None
    ) -> WireObject:
        """Select an equipment slot or unload equipped items."""
        return encode_result(self._game.equip_best_slot(item_id, expected_revision))

    def preview_equip_best_slot(self, item_id: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_equip_best_slot(item_id))

    def transfer_item(
        self, item_id: str, expected_revision: int | None = None
    ) -> WireObject:
        """Transfer an item using backend destination selection."""
        return encode_result(self._game.transfer_item(item_id, expected_revision))

    def preview_transfer_item(self, item_id: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_transfer_item(item_id))

    def socket_gem(
        self, item_id: str, socket_id: str, expected_revision: int | None = None
    ) -> WireObject:
        """Place one gem into an owned socket."""
        return encode_result(
            self._game.socket_gem(item_id, socket_id, expected_revision)
        )

    def preview_socket_gem(self, item_id: str, socket_id: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_socket_gem(item_id, socket_id))

    def unsocket_gem(
        self, item_id: str, container_id: str, expected_revision: int | None = None
    ) -> WireObject:
        """Extract a gem using backend merge and placement rules."""
        return encode_result(
            self._game.unsocket_gem(item_id, container_id, expected_revision)
        )

    def preview_unsocket_gem(self, item_id: str, container_id: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_unsocket_gem(item_id, container_id))

    def bind_item(
        self, key: str, item_id: str, expected_revision: int | None = None
    ) -> WireObject:
        """Bind a shortcut to an existing identity."""
        return encode_result(self._game.bind_item(key, item_id, expected_revision))

    def preview_bind_item(self, key: str, item_id: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_bind_item(key, item_id))

    def activate_shortcut(
        self, key: str, expected_revision: int | None = None
    ) -> WireObject:
        """Activate backend shortcut business effects."""
        return encode_result(self._game.activate_shortcut(key, expected_revision))

    def preview_activate_shortcut(self, key: str) -> WireObject:
        """Encode a preview without retaining any frontend objects."""
        return encode_result(self._game.preview_activate_shortcut(key))
