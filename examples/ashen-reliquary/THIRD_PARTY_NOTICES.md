# Sources and licenses

- Original frontend inventory (now replaced by the independent TypeScript package): derived from shabbywu/ultralight-godot,
  `samples/Sample 2 - Inventory System`; upstream GPL v3 text is preserved in
  `LICENSE.GPL-3.0.txt`. The host adapter, demo controls, persistence and visual port
  were adapted for this example. No new blanket license is assigned to the Python host.
- Ashen Reliquary artwork: copied from the local Ultralight SDK sample
  `13-game-ui/assets/scenes/ashen-reliquary`. Original item photographs are Cleveland
  Museum of Art Open Access (CC0); textures are derived from Poly Haven / ambientCG
  CC0 assets. The complete source manifest is preserved in
  `web/public/reliquary/LICENSES.md`.
- Grenze / Grenze Gotisch fonts: SIL OFL 1.1, with complete notices next to the fonts
  in `web/public/reliquary/fonts/`.
- Vue: MIT, notice preserved in `licenses/vue-MIT.txt`.
- Vite, legacy polyfills and other build dependencies retain the notices distributed
  in their npm packages. `web/package-lock.json` records the actual resolved versions.
- Native rendering uses ultralight-py and Ultralight; their own distribution terms
  continue to apply. Native libraries are not copied into this example.

The gallery's existing capture provenance is recorded in the repository's
`site/assets/ashen-reliquary-NOTICE.md`. The current native application requires
its authoritative Python backend; the frontend is not a standalone browser game.
