# Sources and licenses

- Original frontend inventory (now replaced by the independent TypeScript package): derived from shabbywu/ultralight-godot,
  `samples/Sample 2 - Inventory System`; upstream GPL v3 text is preserved in
  `LICENSE.GPL-3.0.txt`. The host adapter, demo controls, persistence and visual port
  were adapted for this example. No new blanket license is assigned to the Python host.
- Ashen Reliquary artwork: copied from the local Ultralight SDK sample
  `13-game-ui/assets/scenes/ashen-reliquary`. Original item photographs are Cleveland
  Museum of Art Open Access (CC0); textures are derived from Poly Haven / ambientCG
  CC0 assets. The complete source manifest is preserved in
  `web/public/reliquary/LICENSES.md` (it includes the source sample's other scenes;
  only the Ashen Reliquary section applies to the assets copied here).
- Grenze / Grenze Gotisch fonts: SIL OFL 1.1, with complete notices next to the fonts
  in `web/public/reliquary/fonts/`.
- Vue: MIT. Historical GridStack and uuid license texts remain in `licenses/`; neither is a current runtime dependency.
- Vite, legacy polyfills and other build dependencies retain the notices distributed
  in their npm packages. `web/package-lock.json` records the actual resolved versions.
- Native rendering uses ultralight-py and Ultralight; their own distribution terms
  continue to apply. Native libraries are not copied into this example.

Verification PNGs are generated from the actual AppCore window by `run.py --smoke`
and stored under the showcase root's ignored `.tmp/ashen-reliquary/` directory.
The gallery publishes a native still capture and the standalone browser build; no animation is published. See the repository site/assets/ashen-reliquary-NOTICE.md for capture provenance.
