# Visual Narrative & Storyboard — "Каркас над пропастью"

A section-by-section visual storyboard describing the emotional arc, color moods, transitions, and CSS approaches for the book landing page.

---

## Story Arc Overview

The page follows a five-act narrative structure:

```
Problem → Hero Appears → The Journey → The Result → Call to Action
```

The visitor arrives uncertain and skeptical ("can you really build on a swamp?"), meets the author and his story, walks through the evidence, and leaves convinced enough to buy.

Visual pacing: the page begins dark and dramatic, opens up into warm earthy tones through the middle, and closes with confident warmth and a strong final push.

---

## Section 1: Hero — The Challenge

**Narrative role:** Problem introduction. Establish stakes.

**Visual concept:** Full-viewport hero with a winter photograph of the finished frame house — snow on the ground, warm light in the windows, surrounded by the difficult terrain. The image is overlaid with a dark gradient so the white headline text commands attention. This mirrors the book cover aesthetic: the olive-green and winter tones.

**Emotion:** Awe mixed with skepticism. "He actually did this?"

**Color mood:**
- Background: Dark overlay on photo — `linear-gradient(135deg, rgba(92, 107, 47, 0.85), rgba(45, 45, 45, 0.9))`
- Text: Snow white `#F5F5F0` for headline, cream `#FAF5EE` for subtitle
- CTA button: Warm amber `#D4A843` — a single bright point of warmth against the cold scene

**Layout:** Centered text, vertically and horizontally. The headline is the largest text on the entire page (Merriweather 900, 3.5rem). The CTA button sits below with generous spacing.

**CSS approach:**
```css
.hero {
  min-height: 100vh;
  background: linear-gradient(135deg, rgba(92, 107, 47, 0.85), rgba(45, 45, 45, 0.9)),
              url('/images/hero-house-winter.jpg') center/cover no-repeat;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 2rem;
}
```

**Transition to next section:** The dark gradient fades as the user scrolls. A subtle parallax effect on the background image creates depth. The next section opens on a cream `#FAF5EE` background — a visual exhale.

---

## Section 2: The Problem — Why Swamp Building Is Hard

**Narrative role:** Deepen the problem. Make the reader feel understood.

**Visual concept:** Four problem cards arranged in a 2x2 grid (stacking to single column on mobile). Each card has a muted icon at the top (line-weight style, olive-green), a bold subheading, and a concise paragraph. The background is warm cream, keeping the tone approachable despite the serious content.

**Emotion:** Recognition and validation. "Yes, this is exactly my situation."

**Color mood:**
- Background: Cream `#FAF5EE`
- Cards: Snow white `#F5F5F0` with subtle shadow (`box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08)`)
- Icons: Olive green `#5C6B2F`
- Headings: Charcoal `#2D2D2D`
- Body text: `#3A3A3A`

**Layout:** Section heading centered. Cards in a CSS Grid with `gap: 2rem`. Each card has `padding: 2rem` and `border-radius: 12px`.

**CSS approach:**
```css
.problems-section {
  background-color: #FAF5EE;
  padding: 5rem 2rem;
}

.problem-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 2rem;
  max-width: 1000px;
  margin: 0 auto;
}

.problem-card {
  background: #F5F5F0;
  border-radius: 12px;
  padding: 2rem;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  transition: box-shadow 0.3s ease, transform 0.3s ease;
}

.problem-card:hover {
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
  transform: translateY(-2px);
}
```

**Transition to next section:** A horizontal divider line uses the brand gradient: `linear-gradient(to right, #5C6B2F, #8B9F5C, transparent)`. This olive-green stroke signals a shift from problem to solution.

---

## Section 3: The Solution — What's Inside the Book

**Narrative role:** The hero appears. Present the book as the answer.

**Visual concept:** Seven benefit items in an alternating layout — icon/number on one side, text on the other. Each benefit leads with a large number or statistic (e.g., "1200+" in Merriweather 700, accent color) to create visual rhythm. The section background shifts to snow white to distinguish it from the problem section above.

**Emotion:** Growing confidence. "This book actually covers what I need."

**Color mood:**
- Background: Snow white `#F5F5F0`
- Accent numbers: Warm amber `#D4A843`
- Headings: Primary olive `#5C6B2F`
- Body: `#3A3A3A`
- Subtle left-border on each benefit block: `4px solid #8B9F5C`

**Layout:** Each benefit is a horizontal row with a large number/icon on the left (120px wide) and text on the right. On mobile, stacked vertically.

**CSS approach:**
```css
.solution-section {
  background-color: #F5F5F0;
  padding: 5rem 2rem;
}

.benefit-item {
  display: flex;
  align-items: flex-start;
  gap: 2rem;
  padding: 1.5rem 0;
  border-left: 4px solid #8B9F5C;
  padding-left: 2rem;
  margin-bottom: 1.5rem;
}

.benefit-number {
  font-family: 'Merriweather', serif;
  font-weight: 700;
  font-size: 2.5rem;
  color: #D4A843;
  min-width: 100px;
}
```

**Transition to next section:** Background color shifts from snow white to a warm gradient: `linear-gradient(180deg, #F5F5F0 0%, #FAF5EE 100%)`, easing into the about-author section.

---

## Section 4: The Author — Meet Yuri Podymakhin

**Narrative role:** Build trust. Put a face and story to the book.

**Visual concept:** A two-column layout — author photo on the left, three-paragraph bio on the right. The photo should be a candid shot of Yuri at the construction site or with the finished house (not a studio portrait). Below the bio, small badge-like elements display credentials: "МЭИ", "Плотник 2-го разряда", "5x лауреат журнала «Дом»".

**Emotion:** Trust and respect. "This is a real person with real experience."

**Color mood:**
- Background: Cream `#FAF5EE`
- Photo border: `4px solid #A0784C` (warm wood)
- Credentials badges: Light green `#8B9F5C` background with snow white text
- Motto quote: Olive green `#5C6B2F` italic text, left-bordered with warm amber

**Layout:** Two-column grid (60% text, 40% photo) on desktop. Single column on mobile with photo above text.

**CSS approach:**
```css
.author-section {
  background-color: #FAF5EE;
  padding: 5rem 2rem;
}

.author-grid {
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 3rem;
  max-width: 1000px;
  margin: 0 auto;
  align-items: center;
}

.author-photo {
  border-radius: 12px;
  border: 4px solid #A0784C;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
}

.author-motto {
  border-left: 4px solid #D4A843;
  padding-left: 1.5rem;
  font-family: 'Merriweather', serif;
  font-style: italic;
  color: #5C6B2F;
  font-size: 1.25rem;
  margin-top: 2rem;
}

.credential-badge {
  display: inline-block;
  background-color: #8B9F5C;
  color: #F5F5F0;
  padding: 0.375rem 1rem;
  border-radius: 20px;
  font-family: 'Inter', sans-serif;
  font-size: 0.875rem;
  font-weight: 500;
  margin-right: 0.5rem;
  margin-bottom: 0.5rem;
}
```

**Transition to next section:** A full-width band in charcoal `#2D2D2D` introduces the social proof section — a deliberate contrast shift that commands attention.

---

## Section 5: Social Proof — Numbers and Recognition

**Narrative role:** External validation. Remove remaining doubt.

**Visual concept:** A dark charcoal section with three stat blocks side by side. Each stat has a large number in warm amber (Merriweather 900) with a brief label underneath in cream. Between the stats, subtle vertical divider lines in muted olive. Below the stats: a row showing the FORUMHOUSE logo and the "Дом" magazine reference.

**Emotion:** Impressed reassurance. "The numbers speak for themselves."

**Color mood:**
- Background: `linear-gradient(180deg, #2D2D2D, #3A3A3A)`
- Numbers: Warm amber `#D4A843`
- Labels: Cream `#FAF5EE`
- Divider lines: `rgba(139, 159, 92, 0.3)` (muted light-green)

**Layout:** Three or four stat columns, centered. On mobile, 2x2 grid.

**CSS approach:**
```css
.social-proof-section {
  background: linear-gradient(180deg, #2D2D2D, #3A3A3A);
  padding: 5rem 2rem;
  text-align: center;
}

.stats-grid {
  display: flex;
  justify-content: center;
  gap: 4rem;
  max-width: 900px;
  margin: 0 auto;
}

.stat-block {
  position: relative;
}

.stat-block + .stat-block::before {
  content: '';
  position: absolute;
  left: -2rem;
  top: 10%;
  height: 80%;
  width: 1px;
  background: rgba(139, 159, 92, 0.3);
}

.stat-number {
  font-family: 'Merriweather', serif;
  font-weight: 900;
  font-size: 3rem;
  color: #D4A843;
  line-height: 1;
}

.stat-label {
  font-family: 'Inter', sans-serif;
  color: #FAF5EE;
  font-size: 1rem;
  margin-top: 0.5rem;
}
```

**Transition to next section:** The dark background ends with a hard edge — the cream FAQ section below provides visual relief and signals a shift to practical, answerable questions.

---

## Section 6: FAQ — Answering Doubts

**Narrative role:** Address remaining objections. Remove friction before purchase.

**Visual concept:** Accordion-style FAQ on a clean cream background. Each question is in Merriweather 700, olive green. When expanded, the answer appears in Inter regular, body-text color. A small chevron icon rotates on open/close. The section is narrow (max-width 800px) and centered — a deliberate reduction in width to create a focused, intimate reading experience.

**Emotion:** Reassurance. "Every concern I had is addressed."

**Color mood:**
- Background: Cream `#FAF5EE`
- Question text: Olive green `#5C6B2F`
- Answer text: `#3A3A3A`
- Divider between items: `1px solid rgba(92, 107, 47, 0.15)`
- Active/hover: Question text shifts to warm wood `#A0784C`

**Layout:** Single column, centered, max-width 800px. Each FAQ item has `padding: 1.5rem 0` with bottom border.

**CSS approach:**
```css
.faq-section {
  background-color: #FAF5EE;
  padding: 5rem 2rem;
}

.faq-list {
  max-width: 800px;
  margin: 0 auto;
}

.faq-item {
  border-bottom: 1px solid rgba(92, 107, 47, 0.15);
  padding: 1.5rem 0;
}

.faq-question {
  font-family: 'Merriweather', serif;
  font-weight: 700;
  font-size: 1.125rem;
  color: #5C6B2F;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: color 0.2s ease;
}

.faq-question:hover {
  color: #A0784C;
}

.faq-answer {
  font-family: 'Inter', sans-serif;
  color: #3A3A3A;
  line-height: 1.7;
  padding-top: 1rem;
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.3s ease, padding 0.3s ease;
}

.faq-item.active .faq-answer {
  max-height: 500px;
  padding-top: 1rem;
}
```

**Transition to next section:** Generous bottom padding, then a visual shift to the final CTA section with a warm, enveloping background.

---

## Section 7: Final CTA — Commit to Building

**Narrative role:** The decisive moment. Convert interest into action.

**Visual concept:** A full-width section with a warm gradient background that combines olive and amber tones — the warmest, most inviting section on the page. Centered text with a large heading, a brief reinforcing paragraph, and a prominent CTA button. Below the button, the author's motto in italic. This section feels like a warm handshake — confident, encouraging, decisive.

**Emotion:** Determination and confidence. "I'm ready to start."

**Color mood:**
- Background: `linear-gradient(135deg, #5C6B2F 0%, #3A5A20 50%, #2D2D2D 100%)` — a deep olive-to-charcoal gradient
- Heading: Snow white `#F5F5F0`
- Subtitle: Cream `#FAF5EE` with slight transparency
- CTA button: `linear-gradient(135deg, #D4A843, #A0784C)` with white text
- Motto: Light green `#8B9F5C`, italic

**Layout:** Centered, max-width 700px for text. Button is large (padding 1rem 3rem) and prominent. The section has extra vertical padding (6rem) to give it weight and finality.

**CSS approach:**
```css
.final-cta-section {
  background: linear-gradient(135deg, #5C6B2F 0%, #3A5A20 50%, #2D2D2D 100%);
  padding: 6rem 2rem;
  text-align: center;
}

.final-cta-content {
  max-width: 700px;
  margin: 0 auto;
}

.final-cta-heading {
  font-family: 'Merriweather', serif;
  font-weight: 900;
  font-size: 2.5rem;
  color: #F5F5F0;
  margin-bottom: 1.5rem;
}

.final-cta-subtitle {
  font-family: 'Inter', sans-serif;
  font-size: 1.125rem;
  color: rgba(250, 245, 238, 0.85);
  line-height: 1.7;
  margin-bottom: 2.5rem;
}

.final-cta-button {
  display: inline-block;
  background: linear-gradient(135deg, #D4A843, #A0784C);
  color: #FFFFFF;
  font-family: 'Inter', sans-serif;
  font-weight: 600;
  font-size: 1.125rem;
  padding: 1rem 3rem;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(212, 168, 67, 0.3);
  transition: box-shadow 0.3s ease, transform 0.2s ease;
}

.final-cta-button:hover {
  box-shadow: 0 6px 20px rgba(212, 168, 67, 0.45);
  transform: translateY(-2px);
}

.final-cta-motto {
  font-family: 'Merriweather', serif;
  font-style: italic;
  color: #8B9F5C;
  font-size: 1.125rem;
  margin-top: 2rem;
}
```

---

## Page-Level Visual Notes

### Scroll Animations

Use subtle fade-in-up animations triggered on scroll (via Intersection Observer). Each section's content fades in and shifts up 20px as it enters the viewport. Keep duration at 600ms with `ease-out` timing. Do not animate every element — animate section containers only.

```css
.section-animate {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 0.6s ease-out, transform 0.6s ease-out;
}

.section-animate.visible {
  opacity: 1;
  transform: translateY(0);
}
```

### Background Color Rhythm

The page alternates backgrounds to create visual rhythm and prevent monotony:

1. **Hero** — Dark (photo + gradient overlay)
2. **Problems** — Cream `#FAF5EE`
3. **Solution** — Snow white `#F5F5F0`
4. **Author** — Cream `#FAF5EE`
5. **Social Proof** — Dark charcoal gradient
6. **FAQ** — Cream `#FAF5EE`
7. **Final CTA** — Dark olive gradient

Pattern: Dark → Light → Light → Light → Dark → Light → Dark. The two dark sections (hero and social proof) act as anchors, with the final CTA creating a bookend that mirrors the hero's weight.

### Responsive Breakpoints

| Breakpoint | Width | Notes |
|-----------|-------|-------|
| Mobile | < 640px | Single column, reduced type scale, stacked cards |
| Tablet | 640px–1024px | Two-column grids, slightly reduced spacing |
| Desktop | > 1024px | Full layout, max-width 1200px container |

### Performance Considerations

- Lazy-load all images below the fold.
- Use `loading="lazy"` and `decoding="async"` on `<img>` tags.
- Serve hero image in WebP format with JPEG fallback.
- Preload hero image and Google Fonts for fast first paint.
- Use `font-display: swap` to prevent invisible text during font loading.
