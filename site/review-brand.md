# Brand Review Report: Landing Page

**Reviewed by:** Brand Guardian
**Date:** 2026-03-18
**File reviewed:** `/home/user/agency-agents/site/index.html`
**Branding source:** `/home/user/agency-agents/site/branding.md`

---

## 1. Brand Colors

**Status: PASS**

### Issues Found
None. All color hex values in the Tailwind config (lines 26-53) match the branding guide exactly:
- Primary: `#5B6F3C` / `#8FA76A` / `#3D4E28` -- correct
- Secondary: `#A67C52` / `#C9A87C` / `#7A5A39` -- correct
- Accent: `#B8482A` / `#D4785E` / `#9A3A20` -- correct
- Backgrounds: `#F5F2ED`, `#EAE4D9`, `#2C2A25`, `#D1CCC3` -- correct
- Text: `#2C2A25`, `#6B645A`, `#9B9488` -- correct
- Semantic: info `#4A7C8A`, warning `#D4A43A` -- correct
- No neon, electric, or off-brand colors detected
- No use of pure black (`#000000`) -- uses `#2C2A25` (Peat Dark) as specified

### Fixes Required
None.

---

## 2. Typography / Google Fonts

**Status: NEEDS FIXES (FIXED)**

### Issues Found
Three critical violations were found and corrected:

1. **Wrong Google Fonts import (line 18, original).** The page loaded `Inter` instead of the brand-specified `Merriweather` and `Source Sans 3`.
   - **Original:** `family=Inter:wght@400;500;600;700;800`
   - **Brand requires:** `family=Merriweather:wght@700;900&family=Source+Sans+3:wght@400;600;700`
   - **Status:** FIXED

2. **Wrong Tailwind fontFamily config (lines 54-58, original).** Both `heading` and `body` families pointed to `Inter` instead of the serif/sans-serif pairing from the branding guide.
   - **Original:** `heading: ['Inter', ...]` and `body: ['Inter', ...]`
   - **Brand requires:** `heading: ['Merriweather', 'Georgia', ...]` and `body: ['Source Sans 3', 'Segoe UI', ...]`
   - **Status:** FIXED

3. **Wrong CSS font-family rules (lines 73-82, original).** The `<style>` block hardcoded `Inter` for both `body` and `h1, h2, h3`.
   - **Brand requires:** `body` uses `Source Sans 3`, headings use `Merriweather`
   - **Status:** FIXED

### Fixes Applied
- Google Fonts `<link>` now loads Merriweather (700, 900), Source Sans 3 (400, 600, 700), and JetBrains Mono (400, 500) -- matching branding.md section 2 exactly.
- Tailwind `fontFamily` config now uses the correct font stacks from branding.md section 6.
- CSS `<style>` block now applies `Merriweather` to headings and `Source Sans 3` to body.

---

## 3. Tailwind Config Alignment

**Status: PASS**

### Issues Found
Minor observations (non-blocking):

- The Tailwind config includes `maxWidth`, `borderRadius`, and color tokens that match branding.md section 6.
- The branding guide defines custom `fontSize` tokens (`hero`, `h2`, `h3`, etc.) and custom `spacing` overrides in its Tailwind config. The landing page does not include these in its inline Tailwind config, relying instead on default Tailwind classes (`text-3xl`, `text-4xl`, `py-16`, etc.). This is acceptable since the default Tailwind values are close to the brand spec, but for pixel-perfect adherence, the custom `fontSize` and `spacing` maps from branding.md section 6 should be added.
- The branding guide defines custom `boxShadow` tokens (`card`, `card-hover`, `btn`, `btn-hover`, `btn-active`). The landing page uses Tailwind defaults (`shadow-sm`, `shadow-md`) instead. These are functionally similar but not identical to the brand spec.

### Fixes Required (recommended, not critical)
- Consider adding the `fontSize`, `spacing`, and `boxShadow` sections from branding.md section 6 into the inline Tailwind config for exact brand compliance.

---

## 4. Tone of Communication

**Status: PASS**

### Issues Found
None. The copy across all sections follows the brand voice guidelines:

- **Honest and direct:** "1200 фотографий реальной стройки -- с ошибками и их исправлениями" (line 116)
- **Warm and encouraging:** "Если хотя бы один пункт про тебя -- книга окупится на первой главе" (line 257)
- **Practical:** Every section focuses on tangible content and outcomes
- **Wryly humorous:** "Торф уходит из-под ног" (line 156)
- **Uses informal "ты":** Correct throughout (e.g., "Строишь сам", "Хочешь капитальную постройку")
- **No corporate buzzwords:** No instances of "инновационный", "уникальный", "не упустите шанс"
- **CTA text:** "Хочу книгу" -- matches the approved style from branding.md
- **Exclamation marks:** Only one on the entire page (in the author's motto, which is appropriate)
- **Tagline correctly used:** "Делай хорошо -- плохо само получится!" appears in hero and final CTA

---

## 5. Visual Element Restrictions

**Status: PASS**

### Issues Found
None. The page correctly avoids all restricted visual elements:

- **No stock photos:** Uses SVG placeholder icons for book mockup and author photo (lines 130-138, 376-378). When real images are added, they must follow the "real photos only" rule.
- **No corporate feel:** The design is warm, personal, and documentary in style.
- **No flashy colors:** All colors are from the approved earthy palette.
- **No parallax, particle effects, or auto-playing video:** Only smooth scroll and simple FAQ accordion JS.
- **No carousels or pop-up modals:** Content is laid out in a straightforward scroll.
- **No decorative fonts:** Only brand-approved fonts used.
- **No emoji in headings or body text:** Clean.
- **Icons are stroke-based (outlined):** SVG icons use `fill="none"` and `stroke="currentColor"` with `stroke-width="2"` -- matching the 2px outlined style requirement.

### Notes
- When placeholder images are replaced with real photos, ensure they follow the "documentary style, no stock" rule and use `border-radius: 8px` as specified.

---

## 6. Spacing System

**Status: PASS**

### Issues Found
Minor observation (non-blocking):

- Section padding uses `py-16 md:py-20` throughout (64px / 80px). The branding guide specifies section separation of `64px` (mobile) and `80px` (desktop), which aligns with `py-16` and `py-20`. Correct.
- Card padding uses `p-6` (24px). Branding requires minimum `24px` card padding. Correct.
- The hero section uses `pt-32 pb-20 md:pt-40 md:pb-28`, which provides generous spacing. Acceptable.
- `max-w-content` (1200px) and `max-w-prose` (680px) are defined and used correctly throughout.
- Consistent use of `gap-6`, `gap-4`, `gap-8` for grid spacing.
- The branding specifies an 8px base grid. Tailwind's default spacing scale (where `4` = 16px, `6` = 24px, etc.) aligns with this since all values are multiples of 8px when using the standard tokens.

### Fixes Required
None.

---

## 7. Button Styles, Hover States, and Focus States

**Status: NEEDS FIXES (FIXED)**

### Issues Found

1. **Missing focus ring on nav CTA button (line 96, original).** The navigation "Хочу книгу" button lacked `focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2` while other CTA buttons had them. This is an accessibility violation per the branding guide's button rules ("All buttons must have visible focus:ring states for accessibility").
   - **Status:** FIXED -- added `focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2`

2. **Hero H1 size exceeded brand spec (line 112, original).** The H1 used `text-4xl md:text-5xl` (2.25rem / 3rem), but branding.md specifies H1 hero at `2.5rem` (40px) desktop, `1.75rem` (28px) mobile. Changed to `text-3xl md:text-4xl` (1.875rem / 2.25rem) which is closer to the spec. Note: for exact match, the custom `fontSize` tokens from branding.md should be added to the Tailwind config.
   - **Status:** FIXED -- changed to `text-3xl md:text-4xl`

### Remaining observations (non-critical)
- Button `font-bold` (700) is used throughout. Branding specifies button text as `Source Sans 3, 700, 16px, letter-spacing 0.02em`. The `letter-spacing: 0.02em` is not applied to buttons. Consider adding `tracking-wide` or a custom tracking class to button elements.
- The branding specifies `box-shadow: 0 2px 8px rgba(184, 72, 42, 0.25)` for primary CTA buttons. The page uses Tailwind's `shadow-sm` and `shadow-md` which have different shadow values. For exact brand match, use the custom `boxShadow` tokens from the branding config.

---

## Summary Table

| Category | Status | Critical Issues | Fixed |
|----------|--------|-----------------|-------|
| 1. Brand Colors | PASS | 0 | -- |
| 2. Typography / Fonts | ~~NEEDS FIXES~~ PASS (after fix) | 3 (wrong font loaded, wrong config, wrong CSS) | 3/3 |
| 3. Tailwind Config | PASS | 0 (minor recommendations) | -- |
| 4. Tone of Communication | PASS | 0 | -- |
| 5. Visual Restrictions | PASS | 0 | -- |
| 6. Spacing System | PASS | 0 | -- |
| 7. Buttons / Hover / Focus | ~~NEEDS FIXES~~ PASS (after fix) | 2 (missing focus ring, oversized H1) | 2/2 |

---

## Overall Score: 8 / 10

### Breakdown
- **Colors:** 10/10 -- Perfect match to brand palette, no off-brand values
- **Typography:** 7/10 -- Critical font mismatch found and fixed; custom font size tokens not yet in Tailwind config
- **Tailwind Config:** 8/10 -- Core tokens correct; missing `fontSize`, `spacing`, and `boxShadow` overrides from brand spec
- **Tone:** 10/10 -- Exemplary brand voice throughout all copy
- **Visual Restrictions:** 10/10 -- No violations detected
- **Spacing:** 9/10 -- Consistent and correct; minor alignment opportunities with brand's 8px grid tokens
- **Buttons/Interactions:** 7/10 -- Focus states mostly correct after fix; button letter-spacing and custom shadows not yet applied

### What was fixed in this review
1. Google Fonts import corrected to load Merriweather + Source Sans 3 (was loading Inter)
2. Tailwind fontFamily config corrected for heading and body stacks
3. CSS `<style>` block corrected for heading and body font families
4. Missing `focus:ring` states added to nav CTA button
5. Hero H1 font size reduced to align with brand type scale

### Recommended follow-up actions (non-critical)
1. Add the full `fontSize` map from branding.md section 6 to the inline Tailwind config for exact type scale compliance
2. Add the `spacing` overrides from branding.md section 6 for precise 8px grid alignment
3. Add the `boxShadow` tokens (`card`, `card-hover`, `btn`, `btn-hover`, `btn-active`) for exact button/card shadow compliance
4. Add `tracking-[0.02em]` to all button text for the specified letter-spacing
5. When real images replace placeholders, verify they follow the "real photos only, no stock, documentary style" requirement with `rounded-photo` (8px border radius)

---

*Brand Guardian | Review completed 2026-03-18*
