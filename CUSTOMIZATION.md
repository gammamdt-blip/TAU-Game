# Customizing TAU: practical examples

Everything below was tried against the real game; the numbers quoted are measurements, not estimates.

**Two ways to try a change**

1. *Edit and reload.* Change a number in `config.js`, save, hard-refresh the page (Ctrl/Cmd+Shift+R).
2. *Live in the browser console* (F12). The config is exposed as `TAU.config`, so you can experiment
   without editing a file: `TAU.config.physics.jump.speedDivisor = 1.5`. Most values apply at once
   (jump, generator, hazards, fog, rain). Values that are copied into the runner when a run starts
   (`runner.maxFall`, `runner.gravity`, `runner.startSpeed`, `runner.maxSpeed`) apply from the next run.
   Console changes are lost on reload; copy what you like into `config.js`.

Units: 1 *unit* = 1 pixel of the original game; 1 tile = 16 units; the runner is 12 × 14 units; the screen
shows 270 units from top to bottom. Speeds are in units per second.

---

## Changing jump height

**Where:** `config.js` → `physics`.

| Value | Default | What it does |
|---|---|---|
| `jump.maxHold` | `0.35` | Longest time (s) the button can keep lifting the runner. |
| `jump.speedDivisor` | `2.5` | The hold limit is `min(maxHold, speed / (maxSpeed × speedDivisor))`, so a slow runner can hold for less time than a fast one. **Lower** = longer holds at low speed. |
| `runner.maxFall` | `300` | The runner's terminal fall speed **and** its take-off speed. Raising it makes jumps higher and falls faster. |
| `runner.gravity` | `1200` | Pulls the runner down once the button is released or the hold limit is reached. |
| `jump.earlyTime`, `jump.earlyFactor` | `0.08`, `0.65` | The first 0.08 s of a jump rises at 65 % speed, which makes a tap a small hop. |

**How it works:** while you hold the button, and the hold limit has not run out, the runner rises at a
constant `maxFall` units/s. When you let go, or the limit is reached, gravity takes over, so the
apex is "rise time × take-off speed" plus the coasting distance `maxFall² / (2 × gravity)`. Therefore:

* **Stronger jump** = higher `maxFall`, lower `gravity`, or a longer hold (`maxHold` up, `speedDivisor` down).
* **Gravity** changes how floaty the arc is without changing how long the button works: higher gravity
  means a shorter, snappier jump.

**Measured results** (full-hold jump on a flat roof: apex height / time in the air / horizontal distance
covered at constant speed):

| Setting | at 150 u/s | at 300 u/s | at 600 u/s | at 800 u/s |
|---|---|---|---|---|
| **default** | 25 u / 0.38 s / 57 u | 69 u / 0.70 s / 210 u | 113 u / 1.00 s / 600 u | 127 u / 1.08 s / 864 u |
| `gravity: 900` (floatier) | 31 u / 0.48 s / 72 u | 82 u / 0.87 s / 261 u | 126 u / 1.17 s / 702 u | 141 u / 1.27 s / 1016 u |
| `gravity: 1600` (snappier) | 21 u / 0.30 s / 45 u | 59 u / 0.57 s / 171 u | 102 u / 0.87 s / 522 u | 117 u / 0.97 s / 776 u |
| `jump.speedDivisor: 1.5` | 60 u / 0.63 s / 95 u | 98 u / 0.90 s / 270 u | 127 u / 1.08 s / 648 u | 127 u / 1.08 s / 864 u |
| `runner.maxFall: 360` | 34 u / 0.43 s / 65 u | 92 u / 0.80 s / 240 u | 145 u / 1.10 s / 660 u | 162 u / 1.20 s / 960 u |
| `runner.maxFall: 240` | 17 u / 0.32 s / 48 u | 49 u / 0.60 s / 180 u | 84 u / 0.88 s / 528 u | 95 u / 0.98 s / 784 u |
| `jump.maxHold: 0.2` | 25 u / 0.38 s / 57 u | 69 u / 0.70 s / 210 u | 84 u / 0.80 s / 480 u | 84 u / 0.80 s / 640 u |

For scale: the runner is 14 units tall and a rooftop "step" is at most 1 tile (16 units) higher than the
previous roof.

**Keeping the game balanced.** The level generator knows nothing about your jump: it sizes gaps from the
runner's speed alone. The largest gap it builds is about `0.56 × speed` units (80 u at 150 u/s, 160 u at
300 u/s, 336 u at 600 u/s, 448 u at 800 u/s). Compare that with the distance column above:

* The default jump clears the largest gap by a margin of about 1.3 × at 300 u/s and 1.8 × at 600 u/s.
  (At very low speed the margin is thinner and the runner is still accelerating mid-jump; that is how the
  original plays.)
* `gravity: 1600` leaves only 1.07 × at 300 u/s (171 u against a 160 u gap): tense but possible.
  `gravity: 2000` covers only 150 u at 300 u/s, which is **less** than the largest gap, so some gaps
  become impossible. Don't go that far unless you also shrink the gaps (`generator.gapScale`).
* More powerful jumps make the game easier. To compensate, raise `generator.minGapFraction` or
  `gapScale` (gaps are always long), or `physics.speedRamp` (faster).
* `jump.maxHold: 0.2` caps the jump from 450 u/s upward (the hold limit never exceeds it): it makes
  fast play harder, not slower play.
* Corridors have a ceiling (3 to 6 tiles high): very high jumps bump their heads on it, as in the original.

---

## Changing fog intensity

**Where:** `config.js` → `background.fog`. Three banks, front-most last:

```js
fog: [
  { after: 'skyline_far', y: 108, fx: 0.10, fy: 0.07, alpha: 0.55, drift: 5,  scale: 1.0,  quality: 0 },
  { after: 'skyline_mid', y: 150, fx: 0.22, fy: 0.15, alpha: 0.55, drift: 9,  scale: 1.25, quality: 1 },
  { after: 'world',       y: 168, fx: 1.35, fy: 0.90, alpha: 0.26, drift: 14, scale: 1.7,  quality: 2 }
],
haze: { top: 'rgba(120,130,142,0.00)', bottom: 'rgba(104,114,126,0.24)' },
```

* `alpha` (0 to 1) is the fog's opacity: **the intensity knob.** Each bank sits in front of the layer named
  by `after`, so the first hides the far city, the second the middle city, the third drifts in front of
  the rooftops themselves.
* `drift` is its own sideways speed; `scale` its size; `y` where it hangs; `quality` is the lowest
  Graphics preset index (0 low, 1 medium, 2 high) at which it appears.
* `haze.bottom` tints and lightens the whole lower picture.

**Effect, compared in the game** (all three `alpha`s multiplied by the factor, same scene):

* **× 0.25 (thin):** the full depth of the city shows: far towers, the great dome, antennas, distant
  lights. Crisp, cold, almost clinical.
* **× 1 (default):** layers fade into one another; the far city is a suggestion.
* **× 1.9 (thick):** the skyline is nearly swallowed; only nearby rooftops and the red lights read, and
  the world feels claustrophobic. Contrast between the runner and the background drops, so test
  readability: the runner gets a faint halo (`G.draw`, search for `'cold'`) to help.

Try it live: `TAU.config.background.fog.forEach(f => f.alpha *= 1.9)`. (The `haze` gradient is cached when
the page loads, so a change to `haze` needs a reload.)
Players can switch fog off entirely in Settings → Graphics → FOG.

---

## Changing building heights

"Height" in TAU means how far each roof is above or below the previous one, how tall rooftop structures
are, and how tall corridors are. All three are in the generator.

**Where:** `config.js` → `world` and `generator`.

| Value | Default | Effect |
|---|---|---|
| `generator.maxDropTiles` | `10` | Largest drop (in 16-unit tiles) from one roof to the next. `4` gives a gentler, flatter city: measured largest drop went from 8 to 3 tiles. |
| `generator.maxJumpTiles` | `6` | An upward-jump allowance that is **subtracted** from the drop range, scaled by the runner's current jump ability. Raising it makes big drops rarer. A roof is never more than 1 tile higher than the one before. |
| `generator.hallwayHeights` | 6/5/4/3 tiles | Ceiling height of security corridors by speed: `above: 640` → 6 tiles, `above: 480` → 5, `above: 320` → 4, otherwise 3. Make them taller to give more jumping room. |
| `generator.minGapFraction`, `gapScale`, `gapSpeedFactor` | `0.4`, `0.75`, `0.75` | Gap sizing: `maxGap = speed × gapSpeedFactor / 16 × gapScale` tiles; smallest = `maxGap × minGapFraction`. At 600 u/s, raising `minGapFraction` to `0.8` changed the measured gap range from 8–20 to 16–20 tiles. |
| `generator.minWidthSlow`, `minWidthFast` | `12`, `6` | Smallest building width (tiles) at low / high speed. |
| `world.secondBuilding` | `y: 240`, 8-tile gap | The first drop from the start corridor. |
| `world.height`, `physics.deathY` | `320`, `340` | Height of the playable world; falling below `deathY` ends the run. Keep `deathY` below the lowest possible roof. |
| `generator.craneMinHeight`, `craneMinWidth` | `32`, `400` | Smallest building that may become a crane deck. |

**Visual building height.** Walls are drawn from the roof down past the bottom of the picture, so a lower
roof simply shows more wall. Structures on top of roofs (the boxy and stepped "pyramid" roofs) get their
height from `vint(1, 5)` (1 to 5 tiles) in `Sequence.prototype.reset` in `game.js` (section 10); change
those numbers for taller or shorter rooftop towers. They are scenery with no collision.

**Keeping rooftop gaps playable.**

1. Change gaps and drops in small steps and play: a bigger drop also gives you more time in the air
   (and a stumble if the fall lasts longer than `physics.landing.stumbleFallTime`, 0.235 s).
2. Never let `maxGap` exceed what a jump covers (see the table in *Changing jump height*).
3. Keep corridor ceilings at least 3 tiles so a normal jump fits.
4. The generator already keeps every roof at least one tile above `world.height`. If you lower
   `world.height`, keep `physics.deathY` below it, or the runner can stand on a roof that is "below the
   world".

Try it live: `TAU.config.generator.maxDropTiles = 4` (new buildings are generated ahead of you, so the
change shows up a screen or two later).

---

## Changing the player's appearance

**Files to replace:** `assets/images/player.png` (and nothing else; `assets.js` already describes it).

**Format:** PNG with an alpha channel (transparent background), 32-bit RGBA.

**Dimensions:** the sheet is a grid of **8 columns × 6 rows**; each frame is **24 × 24 game units**, drawn
at **8 pixels per unit**, so each frame is **192 × 192 px** and the whole sheet **1536 × 1152 px**. If you
draw at another resolution (say 16 pixels per unit, a 3072 × 2304 sheet), keep the same grid and set
`ppu: 16` for `player` in `assets.js`; the renderer takes care of the rest.

**Frames, in reading order (left to right, top to bottom), 48 in total:**

| Frames | Row/column positions | Used for |
|---|---|---|
| 0–15 | rows 1–2 | run cycle, played faster as you speed up |
| 16–19 | row 3, columns 1–4 | jump (rising) |
| 20–26 | row 3 column 5 to row 4 column 3 | fall (airborne, descending) |
| 27–37 | row 4 column 4 to row 5 column 6 | tumble (stumble) |
| 38–41 | row 5 column 7 to row 6 column 2 | soft landing |
| 42–47 | row 6, columns 3–8 | death |

The sheet has exactly 48 frames. The animation tables (which frames play, and how fast) are in
`Player`'s constructor in `game.js` (section 7), so if your sheet is laid out differently, edit those
frame lists.

**Alignment.** The runner's hit box is **12 × 14 units** and sits at offset **(4, 10)** inside the 24 × 24
frame. In pixels at 8 ppu that means:

* the **feet must touch the bottom edge** of the 192 × 192 frame (the hit box bottom is the frame
  bottom: 10 + 14 = 24 units);
* the body is centred horizontally (hit box x from 32 to 128 px), roughly the middle 96 px;
* the top of the head at about 80 px from the top for a 14-unit-tall figure (a bit more headroom is fine);
* a backpack or flowing coat may overhang the hit box a little; the collision stays the same.

Draw every frame with the **same feet position** so the character does not bob or slide. Keep the figure
small relative to the city: that is the point of the picture.

**Making the hit box match a different-size character.** Change `physics.runner.width`, `height`,
`offsetX` and `offsetY` in `config.js` (the physics then use the new box; test how it feels, because the level generator does not know about
the change).

**Two ways to make the art:**

1. Paint your own sheet in any editor and save over `player.png`. Keep a copy of the original.
2. Change the figure in `tools/generate-assets.py` (section 6, "PLAYER": a skeleton-driven figure; colour
   from the `PAL` table) and run `python3 tools/generate-assets.py images player`.

**Quick tint example** (recolour the figure without redrawing it):

```python
from PIL import Image
im = Image.open("assets/images/player.png").convert("RGBA")
r, g, b, a = im.split()
im = Image.merge("RGBA", (r.point(lambda v: min(255, v + 70)), g, b, a))   # example: a warmer, redder figure
im.save("assets/images/player.png")
```

Reload the page: the runner's reflection on wet roofs, the faint halo and the corridor lighting are all
automatic.

---

## More quick recipes

* **No rain:** Settings → Graphics → RAIN, or `weather.rainCount: 0`. Heavier: `rainCount: 520`.
* **Slower start / faster pace:** `physics.runner.startSpeed`, and the table `physics.speedRamp`
  (each row is `{ below: speed, accel }`).
* **More special buildings:** `generator.specialEvery: [2, 4]` (corridors, crumbling roofs, missile roofs and
  cranes appear every 2 to 4 buildings).
* **Cut hazards:** `generator.obstacleChance: 0`, `roofObstacleChance: 0`, `droneChance: 0`.
* **Longer warning before missiles:** `hazards.missile.triggerDistance: 640`.
* **Rename the game / change the tagline:** `config.js` → `game` (`name`, `tagline`, `gameOverTitle`); also the
  page `<title>` and the Credits text in `index.html`.
* **Make the screen shake less:** Settings → Gameplay → SCREEN SHAKE, or the default in
  `defaults.gameplay.shake` (0 to 1).
