/* ==========================================================================
 * TAU - asset manifest and loader
 *
 * Every image, sound and font the game uses is listed here, and nothing else
 * refers to a file name. To replace a piece of art or a sound, drop a new file
 * with the same name into assets/ (or change the file name below) - no gameplay
 * code has to change. See docs/ASSET_GUIDE.md.
 *
 * IMAGE ENTRIES
 *   file    file name inside assets/images/ (default: "<id>.png")
 *   ppu     source pixels per world unit (default 8). A 64 x 14 unit roof strip drawn at
 *           8 ppu is a 512 x 112 pixel image. The renderer picks a smaller copy (a mip)
 *           when the screen shows fewer device pixels per unit than the file holds, so
 *           art is always minified, never blurred up, on screens up to 4K.
 *   fw, fh  size of one animation frame in units (for sprite sheets)
 *   cols    frames per row in the sheet
 *   lights  [x, y, 'red'|'white'] positions (units from the top-left) of warning lights
 *           that the renderer makes blink
 *   native  true for pictures drawn 1:1 with no mip chain (sky, grain, interface icons)
 *   edge    CSS colour that fills the space under a skyline layer. Leave it out to have
 *           it measured from the picture (works over http only; file:// falls back to charcoal)
 *
 * The numbers must match the PPU used by tools/generate-assets.py when you regenerate.
 * ========================================================================== */
const ASSETS = {
  paths: {
    images: 'assets/images/',
    audio: 'assets/audio/',
    fonts: 'assets/fonts/',
    audioBundle: 'assets/audio/audio-data.js'
  },

  images: {
    // ---- backdrop
    sky:             { file: 'sky.jpg', ppu: 1, native: true },
    skyline_atmos:   { ppu: 1.5, edge: 'rgb(136,144,154)' },
    skyline_far:     { ppu: 2, edge: 'rgb(122,130,140)' },
    skyline_mid:     { ppu: 3, edge: 'rgb(104,111,121)' },
    skyline_near:    { ppu: 4, edge: 'rgb(74,80,90)' },
    fog_bank:        { ppu: 3 },

    // ---- building surfaces (tiled)
    wall_slit:       { ppu: 8 },
    wall_grid:       { ppu: 8 },
    wall_panel:      { ppu: 8 },
    wall_rib:        { ppu: 8 },
    roof_a:          { ppu: 8 },
    roof_b:          { ppu: 8 },
    roof_c:          { ppu: 8 },
    floor_plate:     { ppu: 8 },
    floor_grate:     { ppu: 8 },
    hall_wall:       { ppu: 8 },
    fence:           { ppu: 8 },
    railing:         { ppu: 8 },

    // ---- rooftop props (bottom-aligned)
    antenna_a:       { ppu: 8, lights: [[11, 1.2, 'red']] },
    antenna_b:       { ppu: 8, lights: [[8, 1, 'red']] },
    antenna_c:       { ppu: 8, lights: [[14, 12, 'red']] },
    antenna_d:       { ppu: 8, lights: [[20, 1.2, 'red'], [20, 66, 'red']] },
    antenna_e:       { ppu: 8, lights: [[12, 4, 'red'], [20, 10, 'white']] },
    tower_surveillance: { ppu: 8, lights: [[9, 2.2, 'red']] },
    cctv_pole:       { ppu: 8, lights: [[9.2, 8.8, 'red']] },
    vent_a:          { ppu: 8 },
    vent_b:          { ppu: 8 },
    pipes_a:         { ppu: 8 },
    pipes_b:         { ppu: 8 },
    skylight:        { ppu: 8 },
    access_hut:      { ppu: 8, lights: [[10.5, 8.5, 'white'], [31, 7, 'red']] },
    tank:            { ppu: 8 },
    crates:          { ppu: 8 },
    floodlight:      { ppu: 8, lights: [[8.5, 6, 'white']] },
    escape:          { ppu: 8, fw: 32, fh: 32, cols: 4 },

    // ---- hazards and set dressing
    obstacles:       { ppu: 8, fw: 14, fh: 14, cols: 4 },
    obstacles2:      { ppu: 8, fw: 14, fh: 14, cols: 4 },
    doors:           { ppu: 8, fw: 12, fh: 19, cols: 4 },
    cracks:          { ppu: 8, fw: 24, fh: 24, cols: 4 },
    missile:         { ppu: 8 },
    crane_deck:      { ppu: 8 },
    crane_column:    { ppu: 8 },
    crane_cab:       { ppu: 8, lights: [[20.5, 0.8, 'red']] },
    crane_winch:     { ppu: 8 },
    crane_hook:      { ppu: 8 },

    // ---- characters and machines
    player:          { ppu: 8, fw: 24, fh: 24, cols: 8 },
    drone:           { ppu: 8, fw: 14, fh: 10, cols: 4 },
    mech_walker:     { ppu: 2, fw: 96, fh: 64, cols: 4 },
    airship:         { ppu: 2 },
    gunship:         { ppu: 4 },

    // ---- particles, foreground, overlays
    smoke:           { ppu: 8, fw: 16, fh: 16, cols: 3 },
    gibs:            { ppu: 8, fw: 6, fh: 6, cols: 6 },
    fg_column:       { ppu: 4 },
    fg_truss:        { ppu: 3 },
    grain:           { ppu: 1, native: true },

    // ---- interface icons (shown with <img data-asset="...">)
    ui_pause:        { ppu: 1, native: true },
    ui_sound_on:     { ppu: 1, native: true },
    ui_sound_off:    { ppu: 1, native: true },
    ui_fullscreen:   { ppu: 1, native: true },
    icon:            { ppu: 1, native: true }
  },

  // Sound ids (assets/audio/<id>.wav). The same sounds are bundled as base64 in
  // assets/audio/audio-data.js so the game can play from a double-clicked index.html.
  audio: [
    'foot1', 'foot2', 'foot3', 'foot4', 'footc1', 'footc2', 'footc3', 'footc4',
    'jump1', 'jump2', 'jump3', 'land', 'tumble', 'wall', 'fall',
    'obstacle1', 'obstacle2', 'obstacle3', 'glass1', 'glass2', 'window1', 'window2',
    'crumble', 'bomb_pre', 'bomb_hit', 'bomb_explode', 'flyby',
    'drone1', 'drone2', 'drone3',
    'start', 'ui_move', 'ui_select', 'ui_back',
    'ambience', 'rain', 'music'
  ],

  fonts: [
    { family: 'TAU Sans', weight: '300', file: 'Inter-Light.otf' },
    { family: 'TAU Sans', weight: '400', file: 'Inter-Regular.otf' },
    { family: 'TAU Sans', weight: '500', file: 'Inter-Medium.otf' }
  ]
};

/* ==========================================================================
 * Loader
 * ========================================================================== */
const Assets = {
  images: {},        // id -> HTMLImageElement
  info: {},          // id -> { ppu, w, h (units), fw, fh, cols, lights, native }
  _mips: {},         // id -> [level0 image, level1 canvas, ...]
  _patterns: {},     // cache of CanvasPatterns
  _edge: {},         // cached edge colours

  url(id) {
    const e = ASSETS.images[id];
    return ASSETS.paths.images + (e.file || id + '.png');
  },

  /** Loads every image and font. Fonts are optional; a missing image rejects. */
  load(onProgress) {
    const ids = Object.keys(ASSETS.images);
    let done = 0;
    const tick = () => { done++; if (onProgress) onProgress(done / (ids.length + 1)); };
    const jobs = ids.map((id) => new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => {
        const e = ASSETS.images[id], ppu = e.ppu || 8;
        this.images[id] = im;
        this.info[id] = {
          ppu, native: !!e.native, w: im.naturalWidth / ppu, h: im.naturalHeight / ppu,
          pw: im.naturalWidth, ph: im.naturalHeight,
          fw: e.fw || im.naturalWidth / ppu, fh: e.fh || im.naturalHeight / ppu,
          cols: e.cols || 1, lights: e.lights || null, edge: e.edge || null
        };
        tick(); resolve();
      };
      im.onerror = () => reject(new Error('Could not load ' + this.url(id)));
      im.src = this.url(id);
    }));
    const fonts = this.loadFonts().then(tick, tick);
    return Promise.all(jobs.concat([fonts])).then(() => { this.bindIcons(document); });
  },

  loadFonts() {
    if (!window.FontFace || !document.fonts) return Promise.resolve();
    return Promise.all(ASSETS.fonts.map((f) => {
      const face = new FontFace(f.family, 'url(' + ASSETS.paths.fonts + f.file + ')', { weight: f.weight });
      return face.load().then((ff) => { document.fonts.add(ff); }).catch(() => { /* falls back to the system sans-serif */ });
    }));
  },

  /** Points every <img data-asset="id"> inside `root` at its file. */
  bindIcons(root) {
    root.querySelectorAll('img[data-asset]').forEach((el) => {
      const id = el.getAttribute('data-asset');
      if (ASSETS.images[id]) el.src = this.url(id);
    });
  },

  // ---------------------------------------------------------------- mip chain
  /** Level (0 = full size) whose resolution is the smallest still >= `dpu` device pixels per unit. */
  level(id, dpu) {
    const inf = this.info[id];
    if (inf.native) return 0;
    let k = 0, ppu = inf.ppu;
    while (ppu / 2 >= dpu * 0.999 && k < 6) { ppu /= 2; k++; }
    return k;
  },

  /** Image or canvas for `id` at mip level k (built lazily, cached). */
  source(id, k) {
    const chain = this._mips[id] || (this._mips[id] = [this.images[id]]);
    while (chain.length <= k) {
      const prev = chain[chain.length - 1];
      const w = Math.max(1, Math.round((prev.naturalWidth || prev.width) / 2));
      const h = Math.max(1, Math.round((prev.naturalHeight || prev.height) / 2));
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const g = c.getContext('2d');
      g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
      g.drawImage(prev, 0, 0, w, h);
      chain.push(c);
    }
    return chain[k];
  },

  /**
   * Source rectangle of frame `i` for drawing at `dpu` device pixels per unit.
   * Returns { src, sx, sy, sw, sh, uw, uh } - draw it as drawImage(src, sx, sy, sw, sh, x, y, uw, uh)
   * with the context scaled to units.
   */
  frame(id, i, dpu) {
    const inf = this.info[id], k = this.level(id, dpu), src = this.source(id, k);
    const f = Math.pow(2, -k), fwp = inf.fw * inf.ppu * f, fhp = inf.fh * inf.ppu * f;
    const col = i % inf.cols, row = Math.floor(i / inf.cols);
    return { src, sx: col * fwp, sy: row * fhp, sw: fwp, sh: fhp, uw: inf.fw, uh: inf.fh };
  },

  /**
   * A repeating CanvasPattern for tiled art. Returns { pat, s } where `s` is the
   * pattern scale (units per source pixel): call pat.setTransform(new DOMMatrix([s,0,0,s,ox,oy])).
   */
  pattern(ctx, id, dpu, mode) {
    const k = this.level(id, dpu), key = id + '|' + k + '|' + (mode || 'repeat');
    let p = this._patterns[key];
    if (!p || p.ctx !== ctx) {
      p = { ctx, pat: ctx.createPattern(this.source(id, k), mode || 'repeat'), s: Math.pow(2, k) / this.info[id].ppu };
      this._patterns[key] = p;
    }
    return p;
  },

  /**
   * Colour that fills the space below a skyline layer. Use the manifest's `edge` colour when it
   * has one (always the case for the skyline layers, so every launch method looks the same);
   * otherwise measure the average of the picture's bottom rows. Reading pixels is refused by
   * browsers for images loaded from file://, so a failed measurement falls back to charcoal.
   */
  edgeColor(id) {
    if (this._edge[id]) return this._edge[id];
    const info = this.info[id];
    if (info && info.edge) return (this._edge[id] = info.edge);
    let col = 'rgb(40,44,50)';
    try {
      const im = this.images[id], c = document.createElement('canvas');
      c.width = 1; c.height = 1;
      const g = c.getContext('2d');
      g.drawImage(im, 0, im.naturalHeight - 6, im.naturalWidth, 6, 0, 0, 1, 1);
      const d = g.getImageData(0, 0, 1, 1).data;
      col = 'rgb(' + d[0] + ',' + d[1] + ',' + d[2] + ')';
    } catch (e) { /* tainted canvas (file://) */ }
    return (this._edge[id] = col);
  },

  // -------------------------------------------------------------------- audio
  /**
   * Resolves to { id: ArrayBuffer } with the raw WAV data of every sound. Served over
   * http(s) the .wav files are fetched; from file:// (where fetch is blocked) the
   * base64 bundle assets/audio/audio-data.js is loaded instead.
   */
  loadAudioBytes() {
    const viaBundle = () => new Promise((resolve, reject) => {
      const done = () => {
        const out = {};
        for (const id of ASSETS.audio) {
          const b64 = window.AUDIO_DATA && window.AUDIO_DATA[id];
          if (!b64) continue;
          const bin = atob(b64), u8 = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
          out[id] = u8.buffer;
        }
        resolve(out);
      };
      if (window.AUDIO_DATA) { done(); return; }
      const s = document.createElement('script');
      s.src = ASSETS.paths.audioBundle;
      s.onload = done;
      s.onerror = () => reject(new Error('Could not load ' + ASSETS.paths.audioBundle));
      document.head.appendChild(s);
    });
    if (location.protocol === 'file:' || typeof fetch !== 'function') return viaBundle();
    return Promise.all(ASSETS.audio.map((id) =>
      fetch(ASSETS.paths.audio + id + '.wav').then((r) => { if (!r.ok) throw new Error(id); return r.arrayBuffer(); })
        .then((buf) => [id, buf])))
      .then((pairs) => { const out = {}; for (const [id, buf] of pairs) out[id] = buf; return out; })
      .catch(viaBundle);
  }
};
