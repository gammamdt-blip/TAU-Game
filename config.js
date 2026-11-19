/* ==========================================================================
 * TAU - central configuration
 *
 * Every number you are likely to want to tweak lives in this file: physics,
 * level generation, hazards, camera, parallax layers, weather, graphics
 * presets, audio mix, UI behaviour and the default player settings.
 * Nothing else needs to be edited to re-balance or re-skin the game.
 *
 * UNITS. The simulation runs in "units" (the original game's pixels). One tile
 * is 16 units; the runner's hit box is 12 x 14 units. Rendering is independent
 * of the simulation: the canvas is sized from the window, the device pixel
 * ratio and the resolution setting, and everything is drawn through a
 * transform that maps units to device pixels. Physics never sees pixels.
 *
 * Loaded as a classic <script> (before assets.js and game.js) so the game also
 * runs when index.html is opened straight from disk.
 * ========================================================================== */
const CONFIG = {

  // ------------------------------------------------------------------ identity
  // The words on the main menu, the game-over screen and the credits come from here
  // (game.js writes them into the page at start-up).
  game: {
    name: 'TAU',
    tagline: 'THE CITY IS WATCHING.',
    gameOverTitle: 'RUN TERMINATED',
    version: '1.0.0'
  },

  // -------------------------------------------------------------- save data keys
  // best distance and settings live in localStorage. The two legacy keys are the
  // ones Rooftop Run used; they are read once so existing records carry over.
  storage: {
    settings: 'tau_settings',
    best: 'tau_best',
    legacyBest: 'rr_best',
    legacyMuted: 'rr_muted'
  },

  // ---------------------------------------------------------------------- view
  // The visible world is `height` units tall (270 = 16:9 with a 480 unit wide base).
  // Wider windows show more of the road ahead, up to `maxAspect`; narrower ones
  // keep `minWidth` units and show more sky/ground instead, down to `minAspect`.
  // Beyond those limits the picture is letterboxed.
  view: {
    height: 270,
    minWidth: 480,
    minAspect: 1.2,
    maxAspect: 2.4,
    // The original game viewed a 480 x 160 window. Screen-shake strength and some
    // level-generation maths are expressed against that reference.
    referenceWidth: 480,
    referenceHeight: 160
  },

  // ----------------------------------------------------------------- rendering
  render: {
    maxPixels: 3840 * 2160,       // cap on the canvas backing store (width x height)
    maxDpr: 3,                    // device pixel ratios above this are not used
    maxStep: 0.02,                // longest physics step in seconds (frames are sub-stepped)
    maxFrameDt: 0.1,              // a longer frame (tab switch, hitch) is treated as 0.1 s
    snapCamera: true,             // snap the camera to whole device pixels (no shimmer)
    // Optional adaptive resolution: lowers the internal resolution when the frame
    // rate drops and restores it when there is headroom. Switch it off in Settings.
    adaptive: { targetFps: 52, minScale: 0.55, step: 0.1, checkEvery: 1.0, headroomSeconds: 5 }
  },

  // ------------------------------------------------------------------- physics
  // These are the original engine's values. Changing them changes how the game plays.
  physics: {
    runner: {
      width: 12, height: 14,            // hit box (units)
      offsetX: 4, offsetY: 10,          // hit box position inside the 24 x 24 unit sprite
      startX: 0, startY: 66,
      startSpeed: 100, accel: 1,
      gravity: 1200, drag: 640,
      maxSpeed: 800,                    // horizontal speed cap (units / s)
      maxFall: 300,                     // terminal fall speed
      wallFall: 1000                    // terminal fall speed after hitting a wall
    },
    // Horizontal acceleration by current speed: the first row whose `below` is
    // greater than the speed applies; the last row has no limit.
    speedRamp: [
      { below: 250, accel: 30 },
      { below: 400, accel: 20 },
      { below: 600, accel: 10 },
      { accel: 4 }
    ],
    // Variable-height jump: the button can be held for min(maxHold, speed / (maxSpeed * speedDivisor)) seconds.
    jump: { maxHold: 0.35, speedDivisor: 2.5, earlyTime: 0.08, earlyFactor: 0.65, airborneBelow: -140 },
    landing: {
      stumbleFallTime: 0.235,           // a fall longer than this (s) makes the runner stumble
      pressVelocity: 300,               // downward push while grounded so the floor keeps reporting contact
      softLandFallTime: 0.06,           // cosmetic landing animation threshold
      softLandDuration: 0.12
    },
    stumbleSpeeds: [150, 300, 500],     // pick tumble animation speed from the current run speed
    obstacleSlow: 0.7,                  // speed multiplier after kicking an obstacle
    overlapBias: 4,                     // collision tolerance (units) for edge landings
    deathY: 340                         // falling below this is fatal
  },

  // ------------------------------------------------------------- world + level
  world: {
    tile: 16,
    height: 320,
    // The runner starts in a long corridor, then drops to the first rooftop.
    startBuilding: { x: -64, y: 80, width: 960 },
    secondBuilding: { gapTiles: 8, y: 240, widthTiles: 42 },
    collisionPadRight: 8                // collision block is this much wider than the drawn roof
  },

  // The procedural generator (same rules as the original).
  generator: {
    specialEvery: [3, 8],               // a special building (corridor/collapse/missile/crane) every N buildings
    firstSpecial: [3, 6],
    gapSpeedFactor: 0.75,               // maxGap = speed * 0.75 / tile * 0.75
    gapScale: 0.75,
    minGapFraction: 0.4,
    hallwayMaxGap: 12,
    screenTilesWidth: 480,              // building width is planned against a 480 unit screen
    minWidthSlow: 12, minWidthFast: 6,  // tiles
    slowSpeedFraction: 0.8,
    maxJumpTiles: 6,
    maxDropTiles: 10,
    hallwayHeights: [ { above: 640, tiles: 6 }, { above: 480, tiles: 5 }, { above: 320, tiles: 4 }, { tiles: 3 } ],
    collapseSpeedDivisor: 75,           // collapse only if width/height <= speed / this
    craneMinHeight: 32, craneMinWidth: 400,
    obstacleChance: 65,                 // % per corridor slot (3 slots)
    roofObstacleChance: 15,             // % per rooftop slot (3 slots)
    droneChance: 35,                    // % of roofs that have a perched drone flock
    droneFlock: { per: 200, density: [0.6, 3], max: 8 }   // flock size = width / per * density, capped
  },

  // ------------------------------------------------------------------- hazards
  hazards: {
    obstacle: { width: 12, height: 2, kickLift: -120, kickGravity: 320 },
    collapse: { startSpeed: 60, accel: 40, maxSpeed: 300 },
    missile: { width: 24, height: 48, triggerDistance: 480, fallSpeed: 800, flashSeconds: 4 },
    glass: { shards: 50, gravity: 500 }
  },

  // -------------------------------------------------------------------- camera
  camera: {
    offsetX: 80,                        // runner sits this far from the left edge while running
    menuOffsetFraction: 0.62,           // ... and this fraction across the screen on the main menu
    introSeconds: 1.6,                  // glide between the two
    feetFraction: 0.6,                  // where the runner's feet sit vertically on a rooftop
    airDrop: 12,                        // extra look-down while airborne (units)
    lookAheadTicks: 1.5,                // look ahead of the runner by this many 60 Hz ticks of travel
    smoothing: 15,                      // catch-up per 60 Hz tick (percent)
    minY: -160, maxY: 120
  },

  // ---------------------------------------------------------------- background
  // y = position of the layer's top at the reference camera height (screen units);
  // fx / fy = how much of the camera movement the layer follows (smaller = farther away).
  background: {
    referenceCameraY: -88,
    skyDrift: 0.004,
    layers: [
      { name: 'skyline_atmos', y: -28, fx: 0.03, fy: 0.02 },
      { name: 'skyline_far', y: -34, fx: 0.07, fy: 0.05 },
      { name: 'skyline_mid', y: 36, fx: 0.16, fy: 0.12 },
      { name: 'skyline_near', y: 40, fx: 0.34, fy: 0.25 }
    ],
    // Fog banks drift sideways on their own as well as with the camera.
    fog: [
      { after: 'skyline_far', y: 108, fx: 0.10, fy: 0.07, alpha: 0.55, drift: 5, scale: 1.0, quality: 0 },
      { after: 'skyline_mid', y: 150, fx: 0.22, fy: 0.15, alpha: 0.55, drift: 9, scale: 1.25, quality: 1 },
      { after: 'world', y: 168, fx: 1.35, fy: 0.9, alpha: 0.26, drift: 14, scale: 1.7, quality: 2 }
    ],
    haze: { top: 'rgba(120,130,142,0.00)', bottom: 'rgba(104,114,126,0.24)' },
    // Colossal machines in the haze (between the far and middle skyline layers).
    mech: { count: 2, fx: 0.1, fy: 0.07, y: [52, 70], walkSpeed: 40, scale: 1.7 },
    airship: { fx: 0.04, y: 22, wrap: 3200 },
    gunship: { every: [20, 34], speed: 520, y: [18, 80], shake: [0.012, 1.4], searchlight: true },
    drones: { count: 4, fx: 0.28, y: [40, 150], speed: [14, 34], scale: [0.45, 0.8] },
    // Foreground silhouettes whipping past (original "girders").
    foreground: [
      { name: 'fg_column', fx: [2.2, 3.4], y: -160, gap: [4800, 9600] },
      { name: 'fg_truss', fx: [2.8, 4.2], y: -150, gap: [4800, 9600] }
    ]
  },

  // ------------------------------------------------------------------- weather
  weather: {
    rainCount: 260,                     // streaks at "high", for a 480 x 270 view (scaled by area)
    rainSpeed: [380, 560],
    rainLength: [5, 12],
    rainWind: 70,                       // base sideways drift (units / s)
    rainAlpha: [0.10, 0.28],
    splashesPerSecond: 34,
    steamChance: 30,                    // % of roof vents that smoke
    flicker: 0.04
  },

  // ------------------------------------------------------------------ graphics
  // Presets scale the optional effects. Individual switches in Settings can turn
  // rain / fog / grain / vignette / reflections off whatever the preset says.
  graphics: {
    presets: {
      low:    { rain: 0.35, fogLayers: 1, particles: 0.5, grain: false, reflections: false, lights: false },
      medium: { rain: 0.7,  fogLayers: 2, particles: 0.8, grain: true,  reflections: false, lights: true },
      high:   { rain: 1.0,  fogLayers: 3, particles: 1.0, grain: true,  reflections: true,  lights: true }
    },
    resolutionScales: [0.5, 0.75, 1],
    grainAlpha: 0.07,
    vignetteStrength: 0.55
  },

  // --------------------------------------------------------------------- audio
  audio: {
    masterGain: 1.0,
    music: { level: 0.38, deathLevel: 0.12 },
    ambience: { level: 0.55, speedBoost: 0.5, indoorCutoff: 700 },
    rain: { level: 0.35, indoor: 0.12 },
    footstepVolume: 0.8,
    dedupeSeconds: 0.035
  },

  // ----------------------------------------------------------------------- UI
  ui: {
    pauseOnBlur: true,
    restartDelay: 0.35,                 // seconds after death before a jump press restarts
    distanceDivisor: 10,                // units per metre shown on the counter
    distanceDigits: 5,                  // game-over screen shows DISTANCE: 00472m
    deathTexts: {
      fall: 'FELL FROM THE ROOFTOPS',
      wall: 'IMPACT WITH STRUCTURE',
      missile: 'DRONE STRIKE'
    }
  },

  // ------------------------------------------------- default (and reset) settings
  defaults: {
    graphics: { quality: 'high', resolution: 1, adaptive: true, rain: true, fog: true, grain: true, vignette: true, reflections: true, fps: false },
    audio: { muted: false, master: 0.8, music: 0.7, effects: 0.9, ambience: 0.8 },
    gameplay: { shake: 1, reduceFlashing: false, pauseOnBlur: true, showDistance: true, showHints: true }
  }
};
