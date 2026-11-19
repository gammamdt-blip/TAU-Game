# Licences and attributions

## TAU: artwork and sound (generated files)

Every image in `assets/images/` and every sound and music file in `assets/audio/` (including the
`audio-data.js` bundle built from them) was generated from scratch by `tools/generate-assets.py`. They are
original work, released under **CC0 1.0 Universal (public domain dedication)**:
<https://creativecommons.org/publicdomain/zero/1.0/>. The only exception is the typeface, below.

No artwork, sound or music from the original *Canabalt*, or from any other game, is included.

## TAU: code

`game.js`, `config.js`, `assets.js`, `index.html`, `style.css` and `tools/generate-assets.py` are new code
(a transformation of the earlier *Rooftop Run* project). The gameplay logic they implement (physics
constants and model, collision resolution, and the procedural building generator) is a re-implementation
derived from the open-source HaxeFlixel Canabalt port at <https://github.com/ninjamuffin99/canabalt-hf>,
which is distributed under the MIT License. As that licence requires, its notice follows. The code in this
project is offered under the same MIT terms.

```
MIT License

Copyright (c) 2024 Finji, LLC

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Typeface

`assets/fonts/Inter-Light.otf`, `Inter-Regular.otf` and `Inter-Medium.otf` are unmodified copies of **Inter**,
Copyright 2016 The Inter Project Authors (<https://github.com/rsms/inter>), licensed under the
**SIL Open Font License, Version 1.1**. The full licence text is in `assets/fonts/OFL.txt`. The game refers
to the font internally by the CSS family name "TAU Sans"; the files themselves are not altered. The same
typeface is used by `tools/generate-assets.py` for the text painted on the in-world billboards.

## Trademarks and unaffiliated status

*Canabalt*® and Finji® are trademarks of Finji, LLC. The original game's artwork and its music
("Run!" and "Daring Escape" by Danny Baranowsky) are separately licensed and are not part of this
project. TAU is an unofficial homage and is not affiliated with or endorsed by Finji, LLC or
Danny Baranowsky.
