# TAU - how the game systems work together

This describes the implementation as it is in `game.js`. Section numbers (`§`) refer to the numbered
banners in that file. All distances are in **units** (the original game's pixels: one tile = 16 units, the
runner's hit box = 12 x 14 units); the screen never appears in a gameplay rule.

Contents: [1 Frame loop](#1-the-frame-loop) · [2 Update order](#2-update-order) · [3 The runner](#3-the-runner)
· [4 Collision](#4-collision) · [5 Level generation](#5-level-generation) · [6 Hazards](#6-hazards)
· [7 Camera](#7-camera) · [8 Rendering](#8-rendering) · [9 Background and weather](#9-background-and-weather)
· [10 Audio](#10-audio) · [11 Input](#11-input) · [12 Interface](#12-interface)
· [13 Settings and save data](#13-settings-and-save-data) · [14 Game states](#14-game-states)
· [15 Debug handle](#15-debug-handle)

---

## 1. The frame loop

`frame()` (§16) runs from `requestAnimationFrame`:

```
raw dt  = time since the last frame
dt      = min(raw, render.maxFrameDt = 0.1 s)       a hitch or tab switch never causes a huge step
if the device pixel ratio changed (window moved to another monitor / zoom): Display.layout()
Input.poll()                                        gamepad + jump button state, once per frame
if dead and the restart delay has passed: show the game-over screen
if not paused:  n = ceil(dt / render.maxStep = 0.02 s);  repeat n times:  G.update(dt / n)
G.draw()
UI.update(dt)                                       HUD numbers, FPS readout
Perf.sample(raw)                                    frame-time statistics, adaptive resolution
```

Consequences:

* Physics advance in steps of **at most 20 ms**, however slow or fast the display runs. A 144 Hz monitor
  runs one 6.9 ms step per frame; a 30 fps machine runs two 16.7 ms steps. The physics never depend on the
  canvas size, the resolution setting or the adaptive scale.
* The ordering "poll input → simulate → draw" is the same every frame; there is no render-side state that
  the simulation reads.

## 2. Update order

`G.update(dt)` (§13), in this order:

1. `time`, `deadTime` and `titleTime` advance.
2. **World:** both `Sequence` objects update (collapse, perched drones, missile, glass windows,
   obstacles, emitters; a sequence that has scrolled off the left edge rebuilds itself ahead). Glass
   shards update against the buildings' collision blocks.
3. **Runner:** `Player.update` (not in the menu). After death the falling body keeps moving by hand.
4. **Distant actors:** walking machines, their smoke, the gunship, background drones, foreground
   silhouettes. These read the camera but never write gameplay state.
5. **Collision:** `separate(block, player)` against every block of both sequences (not in the menu).
6. **Fall whoosh:** plays once when the runner is falling fast below `y = 190`.
7. **Camera** (unless dead).
8. Timers for the intro glide, screen shake, flash.
9. **Effects:** particles, rings, rain, rain splashes, corridor muffling of the sound (`updateEffects`).
10. **Death check:** if the runner is no longer alive the state becomes `dead`, the distance is recorded
    (`Save.record`), the music ducks.

Collision runs *after* the runner has moved and *before* the camera, exactly like the original loop:
the runner integrates a step, is pushed back out of any block it penetrated, and the next step starts
from the corrected position.

## 3. The runner

`Player` (§7) holds position, velocity and a small state machine. Values in `config.js → physics`.

**Horizontal.** The runner always runs. `ax` is chosen from `physics.speedRamp` by current speed:
30 below 250, 20 below 400, 10 below 600, then 4, up to a cap of 800 units/s. Start speed 100. Drag (640)
is one of the original parameters but only acts while acceleration is zero, which in practice is after a
wall hit.

**Vertical.** Gravity 1200, terminal fall speed 300 (`maxFall`). Touching a wall sets the terminal speed to
1000 and cuts all horizontal speed.

**Jumping** (variable height):

* The jump button is down → while `jump` is ≥ 0 the vertical velocity is forced to `-maxFall` (or 65 % of
  that for the first 0.08 s).
* The longest the button can carry the runner is
  `min(0.35 s, speed / (800 × 2.5))`, so the faster you run, the higher you can jump. Releasing early
  (`justReleased`) ends the climb.
* The jump re-arms only when the button has been released while standing on a floor, and walking off a
  ledge cancels it: there is no mid-air jump and no coyote time.

**Landing and stumbling.** `fallTime` accumulates while the vertical speed is at terminal speed. If it
exceeds 0.235 s when the runner touches a floor, the runner stumbles (tumble animation chosen by speed:
thresholds 150/300/500) and screen shake and dust fire. A shorter fall longer than 0.06 s plays the soft
landing animation and sound.

**Obstacles** (§9) cost 30 % of the speed (`obstacleSlow: 0.7`) and trigger the same stumble.

**Death.** Three causes, stored in `player.cause` and shown on the game-over screen:

| Cause | Trigger | Text |
|---|---|---|
| `fall` | `y > physics.deathY` (340) | FELL FROM THE ROOFTOPS |
| `wall` | `touching & WALL` for the first time (running into a taller building) | IMPACT WITH STRUCTURE |
| `missile` | the runner touches a landed missile | DRONE STRIKE |

**Animation.** Frames of the 8 × 6 sheet: 0-15 run (four speeds: 15, 28, 40, 60 fps), 16-19 jump, 20-26 fall,
27-37 tumble (four speeds), 38-41 land, 42-47 die. `Anim` (§6) plays named clips of frame indices.
Footsteps (`foot1-4`, or `footc1-4` on metal floors) are spaced by speed.

**Integration.** `integrate()` (§6) is the original half-step scheme: the velocity is advanced half way,
the position moved with it, the velocity advanced the second half. It is what makes jumps identical to the
original at any frame rate.

## 4. Collision

`separate(block, player)` (§8) is a port of the original engine's swept-AABB separation.

* Every building is one or two axis-aligned **blocks**: `{ x, y, w, h, lastY, vy }`. A corridor adds a
  ceiling block. The block is `world.collisionPadRight` (8) units wider than the drawn roof.
* A quick reject uses the union of the runner's old and new positions against the block's old and new
  positions, so a fast runner cannot tunnel through a block.
* **X axis first.** If the runner moved sideways into the block and was vertically overlapping it in the
  *previous* step, the penetration is removed and `WALL` is flagged, unless the penetration is larger than
  `|move| + overlapBias (4)`, in which case it is treated as a ledge to land on, not a wall.
* **Then Y.** Moving down onto a block flags `FLOOR`, moving up into it flags `CEILING`; the runner takes
  the block's vertical velocity (a crumbling roof carries the runner down with it).
* `Player.update` reads `touching`/`wasTouching`. While grounded it presses `pressVelocity` (300) into the
  floor each step so the next collision keeps reporting `FLOOR`.

Because blocks store `lastY`, moving blocks (the collapsing roof) are handled by the same code as static
ones.

## 5. Level generation

`Sequence` (§10) is one building. **Two** of them leapfrog: while the runner is on one, the other is
placed ahead. When a building's right edge scrolls past the left edge of the screen (`screenX() + w < 0`)
it calls `reset()` and is rebuilt beyond the other one, so there are always two buildings alive and the
city never ends.

### What `reset()` decides

1. **Type.** `GEN.curIndex` counts buildings built so far; `GEN.nextIndex` is the index of the next
   *special* building and `GEN.nextType` its type. Normal buildings are `roof`. When the counts meet, the
   special type is used and the next special is scheduled `generator.specialEvery` (3-8) buildings later
   with a random type from corridor / collapse / missile / crane. The first special is 3-6 buildings in
   and is always a collapse.
2. **The first two buildings are fixed:** a 960-unit start corridor at `y = 80` (with two obstacles), then
   a roof 8 tiles beyond it, 42 tiles wide, at `y = 240`: the first drop.
3. **Gap, width, height** are driven by the runner's current speed `vx`:
   * `maxGap = trunc(vx × 0.75 / 16 × 0.75)` tiles, `minGap = trunc(maxGap × 0.4)`,
     gap = `minGap + r × (maxGap - minGap)` for a random `r`; corridors cap it at 12.
   * minimum width = `screenTiles (32) - gap`, but at least 12 tiles while slower than 80 % of top speed and
     at least 6 tiles otherwise; the width is then random between the minimum and three times it
     (`minW` to `maxW + minW`, where `maxW = 2 × minW`), in whole tiles.
   * how much higher the next roof may be (`maxJ`) is limited by the previous roof's height, the corridor
     height, and by 6 tiles scaled by how long the runner can hold a jump at this speed
     (`jumpLimit / 0.35`); it shrinks as `1 - r`, so a long gap never comes with a big climb.
   * the drop is random from 0 to `maxDrop - maxJ` tiles, at most 10 tiles; a drop of zero becomes a one
     tile climb.
4. **Survivability check.** A *collapse* is only kept if `width / height ≤ speed / 75`; a *missile* roof
   only if `width ≥ speed`; a *crane* only if the roof is at least 32 units high and 400 wide. Otherwise
   the building becomes a normal roof and the next special is rescheduled for the next building.
5. **Corridor height** (`generator.hallwayHeights`) is 6 tiles above 640 units/s, 5 above 480, 4 above
   320, 3 otherwise.

The corridor ceiling, collapse, missile and crane rules are therefore all *speed-aware*, which is what
keeps the generator fair at 100 units/s and at 800.

### What is drawn

A building's art is **not** a bitmap. `reset()` calls `DL.begin(seq)` and then `DL.pat / spr / prop /
rect / grad / box`, which append *display-list operations* (tiled texture fills, sprites, rectangles,
gradients) to `seq.ops` and blinking lights to `seq.lights`. `Sequence.draw()` replays the list through
`drawOps()`, skipping anything off screen. Replaying the list every frame at the current resolution
is what makes buildings sharp at any size. All the random choices that only affect looks (which wall
texture, which props, where the vents are, whether there is a fire escape) use the cosmetic generator
`vrnd`; only gap/width/height/drop/type/obstacle/drone decisions use `rnd`.

Rooftop dressing (`Sequence.prototype.decorate`): vents (with steam), pipes, antennas, skylights, access
huts, tanks, crates, CCTV poles, surveillance towers, floodlights, railings and fences, in three roof
styles (flat, box-structure, stepped pyramid). Every prop is bottom-aligned on a ground line, and its
warning lights come from the manifest (`lights` in `assets.js`).

## 6. Hazards

All in §9, all driven from `Sequence.update`:

| Hazard | Where | Behaviour |
|---|---|---|
| `Obstacle` (debris) | 3 chances per corridor (65 % each), 3 per roof (15 %) | 12 × 2 unit trigger on the floor. Hit: runner stumbles, loses 30 % speed, the debris is kicked away spinning. |
| `GlassWindow` + `Shard` | both ends of every corridor | Pane 32 units wide. Running into it shatters it into 50 shards (scaled by the particle level) that fall and bounce on the building blocks. No gameplay effect except sound and shake. |
| `Drone` (perched) | 35 % of non-corridor roofs, flock size grows with width | Lifts off when the runner passes its trigger point. Cosmetic: no collision. |
| Crumbling building | `COLLAPSE` type | The moment the runner passes the building's left edge the main block starts to fall: start speed 60, +40/s, cap 300 units/s, carrying runner and perched drones down. Dust and rubble emitters start. |
| `Missile` | `BOMB` type | When the runner is within 480 units, a missile drops at 800 units/s onto the roof, lands, tumbles and waits. Touching it kills the runner (`missile`), vaporises the roof (`aftermath()`: blocks removed, rubble burst) and flashes the screen. |
| Crane | `CRANE` type | A tall roof with a metal deck (louder footsteps), column, cab, winch and hook. It is cosmetic apart from being a high, wide building. |

Falling off any building is the fourth way to die (`deathY`).

## 7. Camera

`G.cameraTarget()` and `G.updateCamera()` (§13). The camera is `{ x, y }` in world units.

* **Target:** x = runner x + 0.5 − offset; y = runner feet − `view height × feetFraction (0.6)`, plus
  `airDrop (12)` while airborne.
* **Offset:** the runner sits 80 units from the left edge while running and 62 % across the screen on the
  main menu; the two framings glide into each other over `introSeconds (1.6)`.
* **Look-ahead:** `1.5 ×` the distance the runner covered per 60 Hz tick, so a fast runner sees further.
* **Smoothing:** the camera closes `smoothing (15 %)` of the gap per 60 Hz tick (frame-rate independent:
  `1 - (1 - 0.15)^(dt × 60)`).
* **Clamp:** y stays within `minY (-160)` and `maxY (120)`.
* The camera is **not** updated after death, so the body falls out of frame.
* At draw time the camera is **snapped to whole device pixels** (`Display.snapX/snapY`) so tiled textures
  and sprites do not shimmer while scrolling.

## 8. Rendering

### Resolution independence (§3)

`Display.layout()` (on start, resize, fullscreen change, DPR change, setting change):

```
logical view    height 270 units; width 480 or more, from the window aspect ratio clamped to 1.2 ... 2.4
CSS size        the largest picture of that shape that fits the window (letterboxed beyond the limits)
backing store   CSS size × devicePixelRatio (≤ 3) × Settings resolution (50/75/100 %) × adaptive scale,
                shrunk to at most 3840 × 2160 pixels
transform       ctx.setTransform(dx, 0, 0, dy, 0, 0)   dx, dy = backing pixels per unit
```

So a 1920 × 1080 window at DPR 1 draws into 1920 × 1080 pixels, a 4K display into 3840 × 2160, a phone in
landscape into its native pixels, and none of it changes the simulation.

**Mip chain (`assets.js`).** Each image is stored at a pixels-per-unit density (`ppu`). `Assets.level()`
picks the smallest copy whose density is still ≥ the screen's pixels per unit; smaller copies are built on
first use by halving with high-quality filtering. Art is therefore always *minified*, never blurred up,
at any resolution up to 4K (8 px/unit art is 1:1 at 3840 × 2160). The distant backdrop layers are stored
at lower densities (1.5-4 px/unit) and are magnified at 4K; this is the one place where art is below
native resolution (see [CHANGELOG.md](../CHANGELOG.md#known-limitations)).

**Adaptive resolution (`Perf`).** Every second the average FPS is checked. Below 52 fps the adaptive
scale drops by 0.1 (not below 0.55); with 4+ fps of headroom for 5 s it rises again. It is disabled in
the menu, can be switched off in Settings, and only changes the backing-store size, never the simulation.

### Draw order (`G.draw`, §14)

1. Dark fill, then the **sky** backdrop, covering the view and drifting slightly with the camera.
2. Screen shake begins here: everything after the sky is offset together.
3. **Distant city**, back to front, each layer wrapping horizontally and moving at its own fraction of the
   camera speed (`background.layers`): atmospheric skyline → (airship) → far skyline → (fog bank 1,
   smoke, walking machines) → mid skyline → (fog bank 2, background drones) → near skyline (gunship).
   Fog banks with `quality ≥` the current fog level are skipped.
4. A **haze** gradient over the whole picture, denser at the bottom.
5. **World** (camera transform): both buildings, glass shards, the runner's cold halo, the runner with a
   faint inverted copy on wet roofs, then the buildings' front layer (glass panes, rubble and dust
   emitters), rain splashes, particles (dust, sparks, shock rings) and the blinking lights.
6. The nearest **fog bank**, then the **foreground** columns and trusses.
7. **Screen-space atmosphere:** rain (fades while the runner is inside a corridor), vignette, film grain
   (a 256 px tile with a random offset each frame), and the white flash.

### Quality presets (`graphics.presets`)

| | rain | fog banks | particles | grain | reflections | glow lights |
|---|---|---|---|---|---|---|
| low | 35 % | 1 | 50 % | off | off | off |
| medium | 70 % | 2 | 80 % | on | off | on |
| high | 100 % | 3 | 100 % | on | on | on |

The individual switches in Settings (rain, fog, wet reflections, grain, vignette) can switch an effect
off whatever the preset says (`Fx.refresh()` combines them). Cosmetic randomness is separate from
gameplay randomness, so no setting changes how a run plays.

## 9. Background and weather

* **Skyline layers** (§11) are wide strips drawn twice side by side so they wrap. Each has a vertical
  anchor (`Back.y`) that keeps it in the same place relative to the rooftops on any view height. The
  space below a strip is filled with the strip's `edge` colour so tall views never show a gap.
* **Walking machines** (`Walker`): two giant mechs between the far and mid layers. They idle, walk
  (40 units/s), stop and fire, venting smoke through five shared `Emitter`s; when they leave the screen
  they come back from the other side later.
* **Airship:** one, drifts slowly between the atmospheric and far layers.
* **Gunship:** appears every 20-34 s (first after 8-16 s), crosses the sky at about 520 units/s with a
  searchlight raking the roofs, shakes the picture a little and plays `flyby`.
* **Background drones:** four small flying drones with blinking red lights.
* **Foreground:** a column and a truss that whip past at 2.2-4.2× camera speed, reappearing at a new depth
  after a random 4 800-9 600 units.
* **Rain** (`Rain`, §12): two layers of streaks (60 % far, 40 % near) in screen space, count scaled by
  screen area and rain level, slanting back as the camera speeds up. Rain splashes are ellipses placed on
  whichever rooftop is visible.
* **Lights** (`Light`): soft glow sprites (red, white, warm, cold) drawn additively. Rooftop and corridor
  lights come from the building's `lights` list; the runner's faint cold halo keeps a dark figure readable
  against dark roofs.

## 10. Audio

`Snd` (§4) is a Web Audio mixer.

```
effects ──► sfx bus  ───────────────────────────────┐
music   ──► music bus ──────────────────────────────┤
ambience ─► amb bus ─┐                               ├─► master ─► speakers
rain    ──► rain bus ─┴─► low-pass filter ──────────┘
```

* **Unlocking.** Browsers keep audio locked until a user gesture. `Snd.unlock()` is called from the first
  key press, pointer press or button click. Before that, `play()` calls are ignored. The raw sound data
  is fetched (http) or read from `audio-data.js` (file://) at start-up and decoded after the unlock.
* **Loops:** `ambience` (industrial hum, wind, distant machinery) and `rain` start as soon as decoding
  finishes; `music` starts with the run.
* **Dynamic mix:** the ambience gets louder with run speed (`ambience.speedBoost`); inside a corridor
  (`G.indoor`) the ambience/rain filter drops to 700 Hz and rain level falls; the music plays at `music.level` (0.38)
  during a run and ducks to `deathLevel` (0.12) when paused, after death and back on the menu.
* **One-shots:** `Snd.play(id, volume)`; the same sound is not retriggered within 35 ms.
* **Levels:** master, music, effects, ambience (Settings) × the config levels; `muted` sets the master to 0.
  `M` toggles mute.
* If audio cannot start (no Web Audio, blocked, decode failure) the game runs silently.

Which events play which sounds: footsteps (`foot1-4`, metal `footc1-4`), jump (`jump1-3`, random, one
variant is silent), land, tumble, wall impact, fall whoosh, obstacle kick (`obstacle1-3`), glass shards
(`glass1-2`), window break (`window1-2`), collapse rumble (`crumble`), missile (`bomb_pre`, `bomb_hit`,
`bomb_explode`), gunship (`flyby`), perched drones (`drone1-3`), run start (`start`) and menu sounds
(`ui_move`, `ui_select`, `ui_back`).

## 11. Input

`Input` (§5) reduces everything to **one jump button**:

| Source | Jump | Notes |
|---|---|---|
| Keyboard | `X` `C` `Z` `Space` `Tab` `Enter` `W` `↑` | `X`/`C`/`Z` also start, restart and resume from menus |
| Mouse / touch | press anywhere on the picture | pointer capture; multiple pointers allowed |
| Gamepad | `A` `B` `X` (buttons 0-2) | first connected pad wins |

`down`, `justPressed` and `justReleased` are computed once per frame in `poll()`. A press that begins and
ends between two frames still counts for one frame (`latched`). Global keys: `P`/`Esc`/gamepad Start
(pause), `M` (mute), `F` (fullscreen). Ctrl/Meta/Alt combinations are ignored so browser shortcuts keep
working. Input is cleared on blur and on pause.

## 12. Interface

`UI` (§15) is plain HTML over the canvas, so text is crisp at any resolution.

* **Screens:** `menu`, `pause`, `over`, `settings`, `credits`. `show(id)` hides the others, updates their
  dynamic text and focuses the first control (or the last-focused one). `go(id)` remembers where `back()`
  should return to.
* **HUD:** distance counter, a speed bar, a "TRACKED" recording dot, pause / mute / fullscreen icon
  buttons, a hint ("HOLD TO JUMP HIGHER", shown for 7 s) and an optional FPS line. The distance is
  `trunc(runner.x / 10)` metres. The page title also shows it.
* **Navigation:** keyboard (arrows or `W`/`S`, `Enter`), mouse/touch, and gamepad (D-pad or left stick,
  `A` select, `B` back, Start pause). Settings tabs move with left/right; sliders and selects with
  left/right on a gamepad.
* **Identity text** (name, tagline, game-over title, version) is written from `config.js → game` at start.

## 13. Settings and save data

* **Settings** (`Settings`, §2) are the `defaults` object from `config.js`, overlaid with what is saved in
  `localStorage` under `tau_settings` (JSON). A saved value is accepted only if its key exists in the
  defaults, its type matches and numbers are finite; then `sanitize()` rejects unknown quality or
  resolution values and clamps volumes and shake to 0-1. Anything else falls back to the default, so an
  old or damaged save can never break the game.
* **Binding:** every element in the settings panel with `data-setting="section.key"` is bound
  generically: checkboxes, `<select>` (with `data-type="number"` for numeric values) and range sliders
  (`data-scale="100"` shows 0-1 values as 0-100 %). Changes are saved at once and `applySetting()` does
  what is needed (relayout, audio levels, HUD, FPS line).
* **Best distance:** `tau_best` (whole metres). Rooftop Run's `rr_best` and its mute flag `rr_muted` are
  read once, so an existing record carries over.
* All storage access is wrapped in `try/catch` (`store`), so private windows or blocked storage just mean
  nothing is remembered.

## 14. Game states

```
menu ──START RUN──► play ──death──► dead ──(0.35 s)──► game-over screen ──TRY AGAIN──► play
  ▲                  │ ▲                                       │
  │              pause / resume                                │
  └──────────────── QUIT TO MENU / MAIN MENU ◄─────────────────┘
```

`G.state` is `menu`, `play` or `dead`; `G.paused` is a separate flag. `G.reset()` rebuilds everything
(runner, both buildings, background actors, effects) and returns to the menu framing; `G.begin()` starts a
run. In the menu the world is alive (weather, background machines) but the runner does not move and the
buildings do not collide.

## 15. Debug handle

`start()` (§16) exposes `window.TAU = { game, input, sound, GEN, config, settings, display, assets, ui,
save, perf, fx, rain, Sequence, Player, separate, rnd }`. The automated tests used it to read positions,
force input, step the simulation by hand and compare against the original engine. It is read-only
convenience for debugging; nothing in the game depends on it. Delete the line if you do not want it.
