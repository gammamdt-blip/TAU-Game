# TAU - project structure

TAU is deliberately small: three scripts, one stylesheet, one HTML page, one asset folder and one
generator. There is no build step, no package manager and no module system. Everything is a classic
`<script>`, which is why the game also runs when `index.html` is opened straight from disk.

```
TAU/
├── index.html                page + every screen's markup
├── style.css                 interface look
├── config.js                 CONFIG: every tunable number
├── assets.js                 ASSETS (manifest) + Assets (loader, mip chain, patterns, audio bytes)
├── game.js                   the engine - 16 numbered sections, one IIFE
├── README.md                 start here
├── CHANGELOG.md              what changed from Rooftop Run, test results, limitations
├── CUSTOMIZATION.md          practical how-tos with measured numbers
├── LICENSE.md                licences and attributions
├── assets/
│   ├── images/               60 files (59 PNG + sky.jpg), all generated
│   ├── audio/                37 WAV files + audio-data.js (base64 copy of the same sounds)
│   └── fonts/                Inter Light / Regular / Medium + OFL.txt
├── tools/
│   └── generate-assets.py    rebuilds every file in assets/images and assets/audio
└── docs/
    ├── PROJECT_STRUCTURE.md  this file
    ├── GAME_SYSTEMS.md       how the systems fit together
    └── ASSET_GUIDE.md        every asset: format, size, replacement procedure
```

## Load order and who knows about whom

`index.html` ends with three script tags, in this order:

1. **`config.js`** defines the global `CONFIG`. It has no dependencies.
2. **`assets.js`** defines `ASSETS` (data) and `Assets` (loader). It does not read `CONFIG`.
3. **`game.js`** reads both and runs. It is wrapped in an IIFE; the only global it adds is `window.TAU`
   (a handle for debugging and automated tests, see [GAME_SYSTEMS.md](GAME_SYSTEMS.md#15-debug-handle)).

The rule that keeps the project easy to change:

| If you want to change... | ...you edit | ...and never need to touch |
|---|---|---|
| a number (speed, gap, fog density, volume, default setting) | `config.js` | `game.js` |
| a picture, sound or font | the file in `assets/` (or its name in `assets.js`) | `game.js` |
| the wording or layout of a screen | `index.html`, `style.css` | `game.js` (unless you add a new control) |
| a rule or behaviour (a new hazard, a new building type) | `game.js` | the other files, except to add a config value or an asset |

## `index.html`

* One `<main id="stage">` that fills the window, containing `<div id="viewport">`: the picture-shaped
  box that `game.js` sizes to the current aspect ratio. Inside it:
  * `<canvas id="game">` is the only drawing surface.
  * `<div id="ui">` is the HTML interface laid over the canvas: the HUD (`#hud`: pause, mute and
    fullscreen buttons, distance counter, speed bar, optional FPS readout, control hint) and five
    screens: `#screen-menu`, `#screen-pause`, `#screen-over`, `#screen-settings`, `#screen-credits`.
  * `#loading` is the "LOADING 42%" line shown until assets are ready.
* Settings controls are bound generically: any element with `data-setting="section.key"` is a settings
  control (see [GAME_SYSTEMS.md](GAME_SYSTEMS.md#13-settings-and-save-data)). Adding a setting is one HTML
  line plus one default in `config.js`.
* Interface icons are `<img data-asset="ui_pause">`; `Assets.bindIcons()` points them at the file named in
  the manifest.
* No external URLs: no CDN, no web fonts, no analytics.

## `style.css`

The surveillance-terminal look: charcoal panels, thin light-grey rules, small caps with wide letter
spacing, warning-red only for state (recording dot, new record). All sizes are in `em`.
`Display.layout()` sets the font size of `#viewport` to one sixtieth of the picture height, so the
interface scales with the picture at any resolution. `[hidden]` screens are removed from layout.
`#ui` itself ignores the pointer (`pointer-events: none`); only buttons, controls and panels turn it
back on, so a tap on the empty picture reaches the game as a jump. The warning colour `--warn` is used
only for state: the blinking recording dot in the HUD, and the "NEW RECORD" line.

## `config.js`

One object, `CONFIG`, in headed sections: `game` (name, tagline, version), `storage` (save keys),
`view`, `render`, `physics`, `world`, `generator`, `hazards`, `camera`, `background`, `weather`,
`graphics`, `audio`, `ui`, `defaults`. Each section has a comment saying what its numbers do and which
ones change how the game *plays* (the `physics`, `world`, `generator` and `hazards` values are the
original game's).

## `assets.js`

* **`ASSETS`** is the manifest. `images` maps an id to `{ file, ppu, fw, fh, cols, lights, native, edge }`
  (all optional except `ppu`; the header comment of the file explains each key), `audio` is the list of
  sound ids, `fonts` the font faces, `paths` the folders.
* **`Assets`** is the loader and the resolution-independence machinery:
  `load()` (images + fonts, with progress), `level()` / `source()` (the mip chain), `frame()` (source
  rectangle of a sprite-sheet frame for the current resolution), `pattern()` (cached tiled
  `CanvasPattern` for building textures), `edgeColor()` (fill under a skyline strip),
  `loadAudioBytes()` (WAV files over http, base64 bundle over `file://`).
* Nothing outside this file contains a file name. (The manifest ids appear in `game.js` and
  `config.js` as plain strings such as `'wall_slit'` or `'fg_column'`.)

## `game.js` - the 16 sections

Search for the `// ====` banners. Each section starts with a numbered title; the list is also in the
file's header comment.

| # | Section | What lives there | Main names |
|---|---|---|---|
| 1 | Constants and utilities | config shortcuts, collision flags, gameplay RNG vs cosmetic RNG, `clamp`/`lerp`/`hit`, safe `localStorage` wrapper | `rnd`, `vrnd`, `store` |
| 2 | Settings and save data | defaults + saved values merged and validated; quality presets resolved into effect levels; best distance | `Settings`, `Fx`, `Save` |
| 3 | Display, DPR, performance | window → logical view → backing store; snapping; frame-time sampling and adaptive resolution; fullscreen | `Display`, `Perf`, `toggleFullscreen` |
| 4 | Audio | Web Audio mixer, buses, loops, muffling in corridors, speed swell | `Snd` |
| 5 | Input | one jump button from keyboard / pointer / gamepad, plus global keys and gamepad menu edges | `Input` |
| 6 | Motion and animation | the original half-step integrator and the frame-clip animator | `computeVelocity`, `integrate`, `Anim` |
| 7 | Player | the runner: jump, speed ramp, stumble, land, die, footsteps | `Player` |
| 8 | Collision and particles | swept AABB separation; sprite particle emitter; rubble / dust factories | `separate`, `Emitter` |
| 9 | Hazards | ankle-high debris, perched drones, corridor glass, drone missile | `Obstacle`, `Drone`, `GlassWindow`, `Shard`, `Missile` |
| 10 | Level generation | building types, the generator rules, building art as display lists, rooftop decoration | `Sequence`, `GEN`, `DL`, `drawOps` |
| 11 | Background | skyline strips, fog banks, walking machines, gunship, background drones, foreground silhouettes | `Back`, `drawSkyline`, `drawFog`, `Walker`, `Gunship`, `BgDrone`, `Foreground` |
| 12 | Weather and lights | glow sprites, vignette gradient, two-layer rain | `Light`, `Rain` |
| 13 | Game state, camera, update | the `G` object: reset, begin, update order, camera, effects | `G` |
| 14 | Rendering | sprite drawing, the full draw order, lights, screen-space atmosphere | `drawFrame`, `G.draw`, `drawPlayer`, `drawLights` |
| 15 | Interface | screen switching, HUD, settings binding, keyboard / gamepad menu navigation | `UI` |
| 16 | Boot and main loop | `frame()`, `start()`, error screen, `window.TAU` | `frame`, `start` |

Everything is documented with JSDoc-style comments (what a function does, what its arguments mean in
*units* versus *pixels*).

### What is simulation and what is presentation

The code is organised so that the rules can be checked without looking at graphics:

* **Simulation (affects play):** sections 5-10 and `G.update`. It runs in logical units, in fixed-size
  sub-steps, and uses the gameplay random generator `rnd` only.
* **Presentation (never affects play):** sections 11, 12, 14 and the particle part of 13. It uses the
  cosmetic generator `vrnd` only, so enabling or disabling fog, rain, grain, lights or particles cannot
  change how a run plays out.
* **Bridge:** `Display` (section 3) is the only place that knows about pixels.

## `tools/generate-assets.py`

Needs Python 3 with Pillow, NumPy and SciPy; **not** needed to play. Builds all of `assets/images/` and
`assets/audio/` (plus `audio-data.js`) from code with fixed random seeds, so every run produces identical
files. It is organised in nine banner-marked sections (toolkit, sky and fog, skyline layers, walls and
roofs, props, player, actors, audio, main). Command line and name filters are described in
[ASSET_GUIDE.md](ASSET_GUIDE.md#8-regenerating-with-the-generator).

## What is *not* in the project

* No server, no `package.json`, no bundler, no transpiler, no tests folder. (The tests that were run
  before delivery are described in [CHANGELOG.md](../CHANGELOG.md#testing).)
* No third-party code. The only third-party files are the Inter font (SIL OFL) in `assets/fonts/`; the
  gameplay rules descend from the MIT-licensed `canabalt-hf` source (see [LICENSE.md](../LICENSE.md)).
