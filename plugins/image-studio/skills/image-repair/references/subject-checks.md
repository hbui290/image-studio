# Subject-specific checks

Read by [image-repair](../SKILL.md) only when the subject is one of these: upscaling, portraits and characters, products, architecture, alpha cutouts, text and logos, marks on tilted surfaces, or web heroes. The general patch and composite steps are in [repair-and-composite.md](repair-and-composite.md). Never search the disk for other artwork: existing images come only from files the user sends or the approved references and logo in `brand show`.

- **Upscaling:** Test a representative crop with a suited model ([Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)); compare at 100% and display size. For whole images use [image-enhance](../../image-enhance/SKILL.md). Upscaling cannot establish unknown details.
- **Portraits and characters:** Use identity references; inspect eyes, hairline, hands, and costume. For face restorers ([CodeFormer](https://github.com/sczhou/CodeFormer)), watch fidelity weights and hair boundaries.
- **Products:** Verify dimensions, material, markings, handles, and reflections against real references. Plausible extra parts are defects.
- **Architecture and backgrounds:** Verify straight lines, vanishing points, repeated units, and continuity across crop boundaries.
- **Alpha cutouts:** Check edges over light and dark backdrops for fringes, missing hair, and holes.
- **Text and logos:** Follow [repair-rules.md](repair-rules.md) for clean plates, alpha extraction, and per-occurrence checks. Composite approved source art or vector after generation; never rely on generators for exact spelling or brand geometry. Rebuild raster marks with [logo to vector](../../image-enhance/references/logo-vector.md).
- **Marks on surfaces:** Tilted surfaces require a measured perspective transform of approved art, checked masks, and light/texture blending. Source corners map to four measured surface corners (`srcX,srcY dstX,dstY`):

  ```bash
  magick base.png \( logo.png -background none -virtual-pixel transparent \
    +distort Perspective '0,0 2540,1450  400,0 2700,1470  400,300 2680,1590  0,300 2520,1565' \) \
    -layers flatten -depth 8 placed.png
  ```

  Keep `+distort` and `-layers flatten` so the warped logo reaches target coordinates. For flat overlays versus scene surfaces, see [BuilderIO logo-composite](https://github.com/BuilderIO/agent-native/blob/main/templates/assets/.agents/skills/logo-composite/SKILL.md).
- **Web heroes:** Inspect desktop and mobile crops, focal subjects, overlay contrast, and file size ([MDN responsive images](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Responsive_images)). For LCP images, check discovery and priority ([web.dev optimize LCP](https://web.dev/articles/optimize-lcp)).
