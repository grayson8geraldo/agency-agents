# Brand Guidelines — "Каркас над пропастью"

Book landing page brand identity for "Каркас над пропастью: строю дом на болоте" by Юрий Подымахин.

---

## Color Palette

| Role | Name | Hex | Usage |
|------|------|-----|-------|
| Primary | Olive Green | `#5C6B2F` | Headers, primary buttons, key accents |
| Secondary | Warm Wood | `#A0784C` | Secondary elements, borders, icons |
| Accent | Warm Amber | `#D4A843` | CTAs, highlights, badges, hover states |
| Background | Cream | `#FAF5EE` | Page background, card backgrounds |
| Dark | Charcoal | `#2D2D2D` | Footer, dark sections, overlays |
| Text | Body Text | `#3A3A3A` | Primary body copy |
| Light Green | Muted Green | `#8B9F5C` | Tags, secondary badges, subtle accents |
| Snow White | Snow | `#F5F5F0` | Alternate section backgrounds, cards |

### Gradient Combinations

- **Hero overlay:** `linear-gradient(135deg, rgba(92, 107, 47, 0.85), rgba(45, 45, 45, 0.9))`
- **CTA button:** `linear-gradient(135deg, #D4A843, #A0784C)`
- **Section divider:** `linear-gradient(to right, #5C6B2F, #8B9F5C, transparent)`
- **Dark section:** `linear-gradient(180deg, #2D2D2D, #3A3A3A)`

---

## Typography

Both typefaces are loaded from Google Fonts with `subset=cyrillic,cyrillic-ext,latin` for full Russian language support.

### Headings — Merriweather

- **Font family:** `'Merriweather', Georgia, 'Times New Roman', serif`
- **Weights:** 700 (bold), 900 (black)
- **Usage:** All headings (h1–h6), pull quotes, hero text
- **Style:** Authoritative, trustworthy, grounded — conveys the seriousness and depth of the book

### Body — Inter

- **Font family:** `'Inter', 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif`
- **Weights:** 400 (regular), 500 (medium), 600 (semi-bold)
- **Usage:** Body text, navigation, buttons, captions, metadata
- **Style:** Clean, highly legible, modern — ensures comfortable reading of long descriptions

### Type Scale

| Element | Size (desktop) | Size (mobile) | Weight | Font |
|---------|---------------|---------------|--------|------|
| Hero heading | 3.5rem (56px) | 2rem (32px) | 900 | Merriweather |
| Section heading (h2) | 2.25rem (36px) | 1.5rem (24px) | 700 | Merriweather |
| Subsection (h3) | 1.5rem (24px) | 1.25rem (20px) | 700 | Merriweather |
| Body large | 1.125rem (18px) | 1rem (16px) | 400 | Inter |
| Body regular | 1rem (16px) | 0.9375rem (15px) | 400 | Inter |
| Caption / small | 0.875rem (14px) | 0.8125rem (13px) | 500 | Inter |
| Button text | 1rem (16px) | 0.9375rem (15px) | 600 | Inter |

### Google Fonts Import

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Merriweather:wght@700;900&display=swap&subset=cyrillic" rel="stylesheet">
```

---

## Tailwind CSS Configuration

```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: '#5C6B2F',
        secondary: '#A0784C',
        accent: '#D4A843',
        cream: '#FAF5EE',
        charcoal: '#2D2D2D',
        'body-text': '#3A3A3A',
        'light-green': '#8B9F5C',
        'snow-white': '#F5F5F0',
      },
      fontFamily: {
        heading: ['Merriweather', 'Georgia', 'Times New Roman', 'serif'],
        body: ['Inter', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      fontSize: {
        'hero': ['3.5rem', { lineHeight: '1.15', letterSpacing: '-0.01em' }],
        'hero-mobile': ['2rem', { lineHeight: '1.2', letterSpacing: '-0.01em' }],
        'section': ['2.25rem', { lineHeight: '1.25' }],
        'section-mobile': ['1.5rem', { lineHeight: '1.3' }],
        'subsection': ['1.5rem', { lineHeight: '1.35' }],
        'body-lg': ['1.125rem', { lineHeight: '1.7' }],
      },
      backgroundImage: {
        'hero-gradient': 'linear-gradient(135deg, rgba(92, 107, 47, 0.85), rgba(45, 45, 45, 0.9))',
        'cta-gradient': 'linear-gradient(135deg, #D4A843, #A0784C)',
        'divider-gradient': 'linear-gradient(to right, #5C6B2F, #8B9F5C, transparent)',
        'dark-gradient': 'linear-gradient(180deg, #2D2D2D, #3A3A3A)',
      },
      borderRadius: {
        'card': '12px',
        'button': '8px',
      },
      boxShadow: {
        'card': '0 4px 20px rgba(0, 0, 0, 0.08)',
        'card-hover': '0 8px 32px rgba(0, 0, 0, 0.12)',
        'button': '0 4px 12px rgba(212, 168, 67, 0.3)',
        'button-hover': '0 6px 20px rgba(212, 168, 67, 0.45)',
      },
    },
  },
}
```

---

## Tone and Voice Guidelines

### Audience

Russian-speaking DIY builders, homeowners, and people planning construction on difficult terrain. Age range 30–60, predominantly male, with varying technical knowledge. They are practical, budget-conscious, and skeptical of marketing promises.

### Voice Principles

1. **Honest and direct.** No exaggeration. The book documents real mistakes alongside successes. Copy should mirror this authenticity. Avoid superlatives like "лучший" or "уникальный" without factual backing.

2. **Practical, not academic.** Use the language of a builder talking to another builder. Short sentences. Concrete numbers. Real examples. Avoid jargon where plain speech works.

3. **Respectful of the reader's intelligence.** Do not condescend. The reader may be a first-time builder, but they are making a serious financial and personal decision. Treat them as a capable adult.

4. **Grounded in evidence.** Every claim should reference something concrete: the 1200 photos, the FORUMHOUSE video with 220k+ views, the "Дом" magazine awards. Let the facts do the selling.

5. **Understated confidence.** The author built a house alone on a swamp. That speaks for itself. The tone should be calm, assured, and matter-of-fact — not boastful.

### Language Notes

- All user-facing copy is in Russian.
- Use "вы" (formal second person) when addressing the reader.
- Keep sentences short. Prefer 15–20 words per sentence.
- Use the author's own motto where appropriate: "Делай хорошо — плохо само получится!"

---

## Visual Rules

### Photography and Imagery

- Feature real construction photos from the book (with permission) — not stock photography.
- Photos should show process, not just results: foundations being poured, frames going up, drainage trenches.
- Winter shots of the completed house on the olive-green background serve as the hero image, matching the book cover aesthetic.
- Apply a subtle warm tint or cream overlay to photos to maintain palette consistency.

### Layout

- Maximum content width: 1200px, centered.
- Section padding: 80px vertical (desktop), 48px vertical (mobile).
- Card padding: 24px–32px.
- Generous white space. Let the content breathe — do not crowd elements.

### Buttons

- Primary CTA: Warm amber `#D4A843` background, charcoal `#2D2D2D` text, `font-weight: 600`. Hover: shift to `cta-gradient`.
- Secondary: Outlined with `#5C6B2F` border, olive-green text. Hover: filled olive-green with white text.
- Border radius: 8px on all buttons.

### Icons

- Use simple, line-weight icons (e.g., Lucide, Heroicons outline).
- Icon color: olive-green `#5C6B2F` or secondary `#A0784C`.
- Size: 24px default, 32px for feature highlights.

### Restrictions

- Do NOT use stock photos of generic houses, happy families, or corporate imagery.
- Do NOT use bright, saturated colors outside the defined palette.
- Do NOT use decorative or script fonts anywhere.
- Do NOT use animations that distract from content. Subtle fade-ins and parallax only.
- Do NOT use more than two font weights on a single screen.
- Do NOT place text over busy photo areas without a gradient overlay ensuring legibility.
- Do NOT use pure white (`#FFFFFF`) as a background — use cream `#FAF5EE` or snow-white `#F5F5F0`.
