# Image Prompts for "Каркас над пропастью: строю дом на болоте"

> Landing page visual assets for the book by Юрий Подымахин.
> Brand palette derived from the book cover: olive-green (#6B7B3A), warm wood (#A0845C), snow-white (#F5F2EB), dark timber (#3B3225), sky-grey (#D4D8D1).

---

## 1. Hero Background Image

**Purpose**: Full-width panoramic hero behind the fold. Atmospheric winter construction scene. Must evoke the feeling of ambition, solitude, and determination in a harsh but beautiful landscape.

### Midjourney Prompt

```
Wide panoramic photograph of a partially-built timber frame house standing on wooden piles above frozen swampy terrain, Russian winter countryside, thick layer of snow covering the ground, tall Scots pine and birch trees in the background, low winter sun casting long golden shadows across the snow, visible wooden frame skeleton of the house with some walls already clad in wood siding, construction tools and lumber stacked nearby, mist rising from the marshland in the distance, atmospheric perspective fading into pale blue horizon, shot on 24mm wide-angle lens, deep depth of field f/11, golden hour winter light, documentary photography style, cinematic composition with rule of thirds, Kodak Portra 400 color rendition, 8k resolution --ar 21:9 --style raw --v 6.1
```

### DALL-E Prompt

```
A wide panoramic photograph of a timber frame house under construction on wooden piles above frozen swampy ground in the Russian winter countryside. Snow covers everything. Tall pine and birch trees stand in the background. The low winter sun creates golden light and long shadows. The wooden frame skeleton is partially clad with natural wood siding. Construction materials are stacked nearby. Mist rises from marshland in the distance. Documentary photography style, shot on wide-angle lens, deep depth of field, cinematic golden hour lighting, Kodak film colors. Aspect ratio 21:9.
```

### CSS Fallback

```css
.hero-background {
  background: linear-gradient(
    135deg,
    #3B3225 0%,
    #6B7B3A 35%,
    #8B9B5A 50%,
    #D4D8D1 75%,
    #F5F2EB 100%
  );
  background-size: 400% 400%;
  animation: heroShift 20s ease infinite;
}

@keyframes heroShift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

/* Alternative static fallback */
.hero-background--static {
  background:
    linear-gradient(180deg, rgba(59,50,37,0.7) 0%, rgba(107,123,58,0.5) 50%, rgba(245,242,235,0.3) 100%),
    linear-gradient(90deg, #3B3225 0%, #6B7B3A 100%);
}
```

---

## 2. 3D Book Mockup Description

**Purpose**: Prominent book visualization in the hero section or buy section.

### Approach: CSS 3D Transform Mockup

The actual book cover image (olive-green with the photo of the frame house in winter snow) already exists. Use CSS to create a 3D perspective book effect rather than generating a new image.

### CSS Book Mockup Implementation

```css
.book-mockup {
  perspective: 1200px;
  display: inline-block;
}

.book-mockup__wrapper {
  position: relative;
  width: 300px;
  height: 430px;
  transform: rotateY(-25deg) rotateX(5deg);
  transform-style: preserve-3d;
  transition: transform 0.6s ease;
  box-shadow:
    15px 15px 40px rgba(59, 50, 37, 0.4),
    5px 5px 15px rgba(59, 50, 37, 0.2);
}

.book-mockup__wrapper:hover {
  transform: rotateY(-15deg) rotateX(3deg);
}

.book-mockup__cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 0 8px 8px 0;
}

/* Book spine */
.book-mockup__spine {
  position: absolute;
  left: -30px;
  top: 0;
  width: 30px;
  height: 100%;
  background: linear-gradient(90deg, #5A6A30, #6B7B3A);
  transform: rotateY(90deg);
  transform-origin: right center;
  border-radius: 8px 0 0 8px;
}

/* Book pages edge */
.book-mockup__pages {
  position: absolute;
  right: -15px;
  top: 5px;
  width: 15px;
  height: calc(100% - 10px);
  background: repeating-linear-gradient(
    180deg,
    #F5F2EB 0px,
    #F5F2EB 1px,
    #E8E5DE 1px,
    #E8E5DE 2px
  );
  transform: rotateY(-90deg);
  transform-origin: left center;
}

/* Decorative shadow underneath */
.book-mockup__shadow {
  position: absolute;
  bottom: -20px;
  left: 10%;
  width: 80%;
  height: 20px;
  background: radial-gradient(ellipse, rgba(59,50,37,0.3) 0%, transparent 70%);
  filter: blur(5px);
}
```

### Description for Image-Based Mockup (if needed)

If a rendered 3D mockup image is preferred over CSS: The book stands at a 25-degree angle, spine facing left, front cover visible showing the olive-green background with a photograph of a wooden frame house in winter snow. The spine is dark olive with the title in white Cyrillic text. Visible page edges on the right side suggest a thick, substantial volume (matching the 1200-photo content). The book casts a soft shadow on a light neutral surface. Warm, slightly directional studio lighting from the upper left creates subtle highlight on the cover surface.

---

## 3. Problem Section Backgrounds

### 3a. Swampy Land with Standing Water

#### Midjourney Prompt

```
Close-up documentary photograph of waterlogged swampy terrain in Russian countryside, dark peat-brown standing water pooling between tufts of marsh grass and sphagnum moss, birch saplings growing from the sodden ground, autumn overcast light creating flat diffused illumination, desaturated earthy color palette of browns and muted greens, feeling of challenge and difficulty, shot on 35mm lens at f/5.6, slightly elevated angle looking down at the flooded ground, editorial documentary style, raw unfiltered aesthetic --ar 16:9 --style raw --v 6.1
```

#### DALL-E Prompt

```
A documentary photograph of waterlogged swampy terrain in the Russian countryside. Dark peat-brown standing water pools between tufts of marsh grass and sphagnum moss. Birch saplings grow from the sodden ground. Overcast autumn light, desaturated earthy browns and muted greens. The scene conveys challenge and difficulty. Shot from a slightly elevated angle, editorial documentary style. Aspect ratio 16:9.
```

#### CSS Fallback

```css
.problem-swamp {
  background:
    radial-gradient(ellipse at 30% 70%, rgba(74, 60, 40, 0.6) 0%, transparent 60%),
    radial-gradient(ellipse at 70% 40%, rgba(107, 123, 58, 0.4) 0%, transparent 50%),
    linear-gradient(180deg, #5A5040 0%, #4A3C28 40%, #3B3225 100%);
}
```

---

### 3b. Difficult Peat Soil Cross-Section

#### Midjourney Prompt

```
Close-up photograph of a freshly dug trench cross-section showing layers of dark peat soil, visible stratification with black organic peat layer on top transitioning to waterlogged clay below, water seeping into the trench from the sides, muddy brown water pooling at the bottom, fibrous root structures visible in the peat, a metal shovel stuck into the edge for scale, overcast diffused daylight, documentary construction photography, shot on 50mm lens f/4, sharp detail throughout, earthy desaturated tones, editorial style --ar 16:9 --style raw --v 6.1
```

#### DALL-E Prompt

```
A close-up photograph of a freshly dug trench showing a cross-section of dark peat soil. Visible layers: black organic peat on top transitioning to waterlogged clay below. Water seeps into the trench from the sides, pooling at the bottom. Fibrous roots visible in the peat. A metal shovel stuck in the edge for scale. Overcast diffused daylight, documentary construction photography, sharp detail, earthy desaturated tones. Aspect ratio 16:9.
```

#### CSS Fallback

```css
.problem-peat {
  background: linear-gradient(
    180deg,
    #6B7B3A 0%,
    #5A5040 10%,
    #3B2A1A 25%,
    #2A1F14 45%,
    #1A1510 60%,
    #4A3C28 75%,
    #8B7B60 90%,
    #A0845C 100%
  );
}
```

---

### 3c. Construction Challenges in Wet Conditions

#### Midjourney Prompt

```
Documentary photograph of a muddy construction site in wet Russian autumn, waterlogged ground with tire tracks filled with brown water, partially laid foundation blocks sitting unevenly on soft ground, scattered wet lumber and construction materials on muddy earth, overcast grey sky, rain-soaked conditions, boots visible at edge of frame standing in mud, atmosphere of determination despite difficult conditions, shot on 28mm wide-angle lens f/8, deep focus, desaturated documentary color grade, raw gritty aesthetic --ar 16:9 --style raw --v 6.1
```

#### DALL-E Prompt

```
A documentary photograph of a muddy construction site in wet Russian autumn. Waterlogged ground with tire tracks filled with brown water. Partially laid foundation blocks sit unevenly on soft ground. Wet lumber and construction materials scattered on muddy earth. Overcast grey sky, rain-soaked conditions. Work boots visible at frame edge standing in mud. Atmosphere of determination despite difficulty. Wide-angle lens, deep focus, desaturated documentary colors. Aspect ratio 16:9.
```

#### CSS Fallback

```css
.problem-wet {
  background:
    repeating-linear-gradient(
      0deg,
      transparent 0px,
      transparent 3px,
      rgba(59, 50, 37, 0.1) 3px,
      rgba(59, 50, 37, 0.1) 4px
    ),
    linear-gradient(
      160deg,
      #7A7A72 0%,
      #5A5A52 30%,
      #4A3C28 60%,
      #3B3225 100%
    );
}
```

---

## 4. Solution / Content Section Images

### 4a. Foundation on Piles/Posts in Swamp

#### Midjourney Prompt

```
Photograph of concrete screw piles foundation being installed on swampy terrain for a frame house, multiple concrete or metal piles rising from marshy ground at uniform height, wooden beam framework resting on top of the piles creating a level platform above the wet ground, early morning light with soft shadows, pine forest in the background, feeling of engineering triumph over difficult terrain, construction documentary photography, shot on 35mm lens f/8, sharp focus throughout, natural warm color palette with olive-green and timber-brown tones, editorial quality --ar 3:2 --style raw --v 6.1
```

#### DALL-E Prompt

```
A photograph of a screw pile foundation being installed on swampy terrain for a frame house. Multiple concrete piles rise from marshy ground at uniform height. A wooden beam framework rests on top, creating a level platform above the wet ground. Early morning light with soft shadows. Pine forest in the background. Feeling of engineering triumph. Construction documentary photography, sharp focus, natural warm olive-green and timber-brown tones. Aspect ratio 3:2.
```

#### CSS Fallback

```css
.solution-foundation {
  background:
    linear-gradient(0deg, #A0845C 0%, #A0845C 15%, transparent 15%),
    repeating-linear-gradient(
      90deg,
      #3B3225 0px,
      #3B3225 8px,
      transparent 8px,
      transparent 60px
    ),
    linear-gradient(180deg, #D4D8D1 0%, #6B7B3A 100%);
}
```

---

### 4b. Frame Construction in Progress

#### Midjourney Prompt

```
Photograph of a wooden timber frame house under construction, exposed wall studs and roof rafters creating geometric patterns of light-colored lumber against blue sky, one man working on the frame visible in silhouette, construction stage showing walls framed but not yet sheathed, plywood floor deck visible, power tools and lumber scattered on the deck, bright clear day with directional sunlight creating strong shadows through the frame structure, shot from ground level looking up at slight angle, 24mm wide-angle lens f/8, construction documentary style, warm natural wood tones contrasting with blue sky, inspiring and heroic feeling --ar 3:2 --style raw --v 6.1
```

#### DALL-E Prompt

```
A photograph of a wooden timber frame house under construction. Exposed wall studs and roof rafters create geometric patterns of light-colored lumber against a blue sky. One person works on the frame in silhouette. Walls are framed but not yet sheathed. Plywood floor deck visible with power tools and lumber. Bright clear day, directional sunlight creates strong shadows through the frame. Shot from ground level looking up, wide-angle lens, construction documentary style. Warm natural wood tones against blue sky, inspiring heroic feeling. Aspect ratio 3:2.
```

#### CSS Fallback

```css
.solution-frame {
  background:
    repeating-linear-gradient(
      90deg,
      #A0845C 0px,
      #A0845C 4px,
      transparent 4px,
      transparent 40px
    ),
    repeating-linear-gradient(
      0deg,
      #A0845C 0px,
      #A0845C 4px,
      transparent 4px,
      transparent 50px
    ),
    linear-gradient(180deg, #87CEEB 0%, #D4D8D1 100%);
}
```

---

### 4c. Drainage System Being Installed

#### Midjourney Prompt

```
Photograph of a drainage system being installed around a house foundation on swampy ground, open trench revealing perforated drainage pipe wrapped in geotextile fabric, gravel bed visible in the trench, French drain construction in progress, wet peat soil visible at trench walls, water draining away through the pipe system, overcast day with soft even lighting, technical construction detail shot, 50mm lens f/5.6, sharp focus on drainage components, documentary editorial style, earthy color palette with browns greens and grey gravel tones --ar 3:2 --style raw --v 6.1
```

#### DALL-E Prompt

```
A photograph of a drainage system being installed around a house foundation on swampy ground. An open trench reveals a perforated drainage pipe wrapped in geotextile fabric on a gravel bed. French drain construction in progress. Wet peat soil visible at trench walls. Water drains through the pipe system. Overcast day, soft even lighting. Technical construction detail shot, sharp focus on drainage components, documentary style. Earthy browns, greens, and grey gravel tones. Aspect ratio 3:2.
```

#### CSS Fallback

```css
.solution-drainage {
  background:
    linear-gradient(180deg, #6B7B3A 0%, #4A3C28 40%, #8B8B8B 60%, #A0A0A0 70%, #4A3C28 80%, #3B3225 100%);
}
```

---

### 4d. Finished Cozy House Interior/Exterior

#### Midjourney Prompt

```
Photograph of a completed beautiful wooden frame house exterior in Russian countryside, natural wood siding with warm honey-brown finish, covered veranda with wooden railings, well-maintained small garden around the house, pine trees surrounding the property, late afternoon golden hour light warming the wood surfaces, smoke gently rising from chimney suggesting warmth and comfort inside, gravel path leading to the front steps, feeling of accomplishment and cozy home, shot on 35mm lens f/5.6, warm Kodak Portra color rendition, shallow depth of field blurring the forest background, editorial architectural photography --ar 3:2 --style raw --v 6.1
```

#### DALL-E Prompt

```
A photograph of a completed beautiful wooden frame house in the Russian countryside. Natural wood siding with warm honey-brown finish. Covered veranda with wooden railings. Small well-maintained garden, pine trees surrounding the property. Late afternoon golden hour light warms the wood surfaces. Gentle smoke rises from the chimney. Gravel path leads to front steps. Feeling of accomplishment and cozy home. Warm Kodak film colors, shallow depth of field blurring the forest background. Architectural photography. Aspect ratio 3:2.
```

#### CSS Fallback

```css
.solution-finished {
  background:
    radial-gradient(ellipse at 50% 50%, rgba(160, 132, 92, 0.6) 0%, transparent 70%),
    linear-gradient(
      180deg,
      #87CEEB 0%,
      #F5D070 20%,
      #6B7B3A 50%,
      #A0845C 70%,
      #3B3225 100%
    );
}
```

---

## 5. About Author Section

**Purpose**: Frame/treatment for the real author photo of Юрий Подымахин.

### Photo Treatment Description

The real author photograph will be used. Apply the following treatment:

- **Shape**: Slightly rounded rectangle (border-radius: 12px), not a circle -- this is a construction/engineering book, not a lifestyle blog.
- **Border**: 3px solid border in warm wood tone (#A0845C) to frame the photo like timber.
- **Shadow**: Warm deep shadow (box-shadow with #3B3225) suggesting depth.
- **Background behind photo**: Subtle wood grain texture or olive-green (#6B7B3A) with slight noise texture.
- **Desaturation**: Apply a subtle warm filter (sepia at 10-15%) to unify the photo with the site palette.

### CSS Treatment

```css
.author-photo {
  border-radius: 12px;
  border: 3px solid #A0845C;
  box-shadow:
    0 8px 30px rgba(59, 50, 37, 0.3),
    0 2px 8px rgba(59, 50, 37, 0.15);
  filter: sepia(12%) saturate(90%);
  transition: filter 0.3s ease;
  max-width: 320px;
}

.author-photo:hover {
  filter: sepia(0%) saturate(100%);
}

.author-section {
  background:
    url("data:image/svg+xml,%3Csvg width='60' height='60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M0 30 Q15 25 30 30 Q45 35 60 30' stroke='%23A0845C' stroke-opacity='0.08' fill='none' stroke-width='1'/%3E%3C/svg%3E")
    repeat,
    linear-gradient(180deg, #F5F2EB 0%, #E8E5DE 100%);
}
```

---

## 6. Social Proof Section

### 6a. Construction Magazine Cover Style

#### Midjourney Prompt

```
Realistic mock-up of a Russian construction magazine cover, glossy printed magazine lying flat on a wooden table surface, cover featuring a photograph of a wooden frame house, Russian Cyrillic headlines in bold typography, professional editorial layout with masthead at top, warm overhead studio lighting creating subtle reflection on glossy paper, shallow depth of field with focus on the magazine, shot on 50mm lens f/2.8, commercial product photography style, warm natural lighting --ar 4:3 --style raw --v 6.1
```

#### DALL-E Prompt

```
A realistic photograph of a Russian construction magazine lying flat on a wooden table. The glossy cover features a photograph of a wooden frame house with bold Cyrillic headlines in professional editorial layout. Warm overhead studio lighting creates subtle reflections on the glossy paper. Shallow depth of field, commercial product photography. Aspect ratio 4:3.
```

#### CSS Fallback

```css
.social-magazine {
  background: #F5F2EB;
  border: 1px solid #D4D8D1;
  border-radius: 4px;
  box-shadow:
    2px 2px 10px rgba(59, 50, 37, 0.15),
    0 1px 3px rgba(59, 50, 37, 0.1);
  padding: 1rem;
  position: relative;
  overflow: hidden;
}

.social-magazine::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, #6B7B3A, #A0845C);
}
```

---

### 6b. FORUMHOUSE Video Screenshot Style

#### Description

For the FORUMHOUSE video reference, use a real screenshot or thumbnail from the actual video with the following treatment:

### CSS Video Thumbnail Treatment

```css
.video-thumbnail {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(59, 50, 37, 0.2);
  cursor: pointer;
  aspect-ratio: 16 / 9;
}

.video-thumbnail img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.video-thumbnail:hover img {
  transform: scale(1.03);
}

/* Play button overlay */
.video-thumbnail::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 64px;
  height: 64px;
  background: rgba(59, 50, 37, 0.8);
  border-radius: 50%;
  border: 3px solid #F5F2EB;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23F5F2EB'%3E%3Cpolygon points='9,6 18,12 9,18'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: 55% 50%;
  background-size: 28px;
  transition: background-color 0.3s ease;
}

.video-thumbnail:hover::after {
  background-color: rgba(107, 123, 58, 0.9);
}
```

---

## 7. Final CTA Section

### Completed House in Golden Hour / Evening Light

#### Midjourney Prompt

```
Beautiful photograph of a completed wooden frame house in Russian countryside at blue hour dusk, warm golden light glowing from windows casting light onto the snow-covered ground, wooden siding with natural finish catching the last amber light of sunset on the horizon, pine tree silhouettes framing the scene, smoke from chimney backlit by the deep blue-purple sky, feeling of warmth safety and home amidst the wilderness, covered veranda with a single warm porch light, pristine snow around the house, shot on 35mm lens f/4, balanced exposure capturing both warm interior glow and cool blue exterior, cinematic color grade with teal and orange contrast, Fuji Velvia color saturation, editorial architectural photography --ar 21:9 --style raw --v 6.1
```

#### DALL-E Prompt

```
A beautiful photograph of a completed wooden frame house in the Russian countryside at blue hour dusk. Warm golden light glows from the windows onto snow-covered ground. Natural wood siding catches the last amber sunset light. Pine tree silhouettes frame the scene. Chimney smoke is backlit by a deep blue-purple sky. Feeling of warmth, safety, and home. Covered veranda with a warm porch light. Pristine snow surrounds the house. Balanced exposure showing warm interior glow and cool blue exterior. Cinematic teal-and-orange color grade. Aspect ratio 21:9.
```

### CSS Fallback

```css
.cta-background {
  background:
    radial-gradient(ellipse at 50% 60%, rgba(255, 200, 100, 0.3) 0%, transparent 50%),
    linear-gradient(
      180deg,
      #1A1530 0%,
      #2A2545 20%,
      #3B3225 50%,
      #6B7B3A 80%,
      #A0845C 100%
    );
}

/* Window glow effect */
.cta-background::before {
  content: '';
  position: absolute;
  top: 40%;
  left: 45%;
  width: 10%;
  height: 8%;
  background: radial-gradient(ellipse, rgba(255, 200, 100, 0.5) 0%, transparent 70%);
  filter: blur(20px);
}
```

---

## 8. OG Image (1200x630)

**Purpose**: Social sharing preview for Facebook, Twitter/X, Telegram, VK, etc.

#### Midjourney Prompt

```
Social media preview banner image, split composition: left third shows a dramatic photograph of a wooden frame house in winter snow with warm glowing windows, right two-thirds is clean olive-green background with space for text overlay, subtle wood grain texture in the green area, warm golden accent strip dividing the photo from the text area, professional book marketing graphic style, clean commercial layout, balanced warm and cool tones --ar 1200:630 --style raw --v 6.1
```

#### DALL-E Prompt

```
A social media preview banner image with a split composition. The left third shows a photograph of a wooden frame house in winter snow with warm glowing windows. The right two-thirds is a clean olive-green background with subtle wood grain texture, leaving space for text overlay. A warm golden accent strip divides the photo from the text area. Professional book marketing style, clean commercial layout. Exactly 1200x630 pixels.
```

#### CSS Fallback (for server-rendered OG)

```css
.og-image {
  width: 1200px;
  height: 630px;
  background:
    linear-gradient(90deg,
      #3B3225 0%,
      #3B3225 33%,
      #A0845C 33%,
      #A0845C 33.5%,
      #6B7B3A 33.5%,
      #6B7B3A 100%
    );
  display: flex;
  align-items: center;
  font-family: 'Georgia', serif;
  color: #F5F2EB;
}
```

### OG Image Text Layout

- **Title**: "Каркас над пропастью" -- large, white, serif font (Georgia or PT Serif)
- **Subtitle**: "строю дом на болоте" -- smaller, #D4D8D1, italic
- **Author**: "Юрий Подымахин" -- medium, #A0845C accent color
- **Badge**: "1200+ фото" -- small rounded pill in #A0845C on dark background

---

## 9. Favicon

### Concept

A minimal house frame icon -- the outline of a house showing exposed timber frame structure (studs visible), suggesting both "house" and "construction/frame." Olive-green (#6B7B3A) as the primary color on transparent background.

#### SVG Favicon Code

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <!-- Roof -->
  <path d="M16 3 L3 14 L6 14 L6 28 L26 28 L26 14 L29 14 Z" fill="none" stroke="#6B7B3A" stroke-width="2" stroke-linejoin="round"/>
  <!-- Frame studs -->
  <line x1="11" y1="14" x2="11" y2="28" stroke="#6B7B3A" stroke-width="1.5"/>
  <line x1="16" y1="8" x2="16" y2="28" stroke="#6B7B3A" stroke-width="1.5"/>
  <line x1="21" y1="14" x2="21" y2="28" stroke="#6B7B3A" stroke-width="1.5"/>
  <!-- Horizontal beam -->
  <line x1="6" y1="20" x2="26" y2="20" stroke="#6B7B3A" stroke-width="1.5"/>
  <!-- Foundation piles -->
  <line x1="8" y1="28" x2="8" y2="31" stroke="#A0845C" stroke-width="2" stroke-linecap="round"/>
  <line x1="16" y1="28" x2="16" y2="31" stroke="#A0845C" stroke-width="2" stroke-linecap="round"/>
  <line x1="24" y1="28" x2="24" y2="31" stroke="#A0845C" stroke-width="2" stroke-linecap="round"/>
</svg>
```

#### ICO Generation Note

Generate the favicon at 16x16, 32x32, and 48x48 sizes. For the 16x16 version, simplify to just the house outline and a single center stud to maintain legibility.

---

## 10. SVG Section Icons

All icons use a consistent 24x24 viewBox, 1.5px stroke width, olive-green (#6B7B3A) stroke color, no fill. Designed for inline embedding in HTML.

---

### Foundation / Base Icon

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#6B7B3A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <!-- Ground level beam -->
  <rect x="2" y="10" width="20" height="3" rx="0.5"/>
  <!-- Piles going into ground -->
  <line x1="5" y1="13" x2="5" y2="21"/>
  <line x1="12" y1="13" x2="12" y2="21"/>
  <line x1="19" y1="13" x2="19" y2="21"/>
  <!-- Pile bases (flanges) -->
  <line x1="3" y1="21" x2="7" y2="21"/>
  <line x1="10" y1="21" x2="14" y2="21"/>
  <line x1="17" y1="21" x2="21" y2="21"/>
  <!-- Ground surface (wavy for swamp) -->
  <path d="M1 16 Q4 14.5 7 16 Q10 17.5 13 16 Q16 14.5 19 16 Q22 17.5 23 16" stroke-opacity="0.4"/>
</svg>
```

---

### Frame / Structure Icon

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#6B7B3A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <!-- Roof peak -->
  <path d="M12 2 L3 10 L21 10 Z"/>
  <!-- Left wall stud -->
  <line x1="5" y1="10" x2="5" y2="22"/>
  <!-- Right wall stud -->
  <line x1="19" y1="10" x2="19" y2="22"/>
  <!-- Center stud -->
  <line x1="12" y1="6" x2="12" y2="22"/>
  <!-- Mid studs -->
  <line x1="8.5" y1="10" x2="8.5" y2="22"/>
  <line x1="15.5" y1="10" x2="15.5" y2="22"/>
  <!-- Bottom plate -->
  <line x1="3" y1="22" x2="21" y2="22"/>
  <!-- Mid rail -->
  <line x1="5" y1="16" x2="19" y2="16"/>
</svg>
```

---

### Drainage / Water Icon

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#6B7B3A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <!-- Pipe cross-section -->
  <rect x="2" y="8" width="20" height="5" rx="2.5"/>
  <!-- Pipe holes (perforated) -->
  <circle cx="6" cy="10.5" r="0.8" fill="#6B7B3A"/>
  <circle cx="10" cy="10.5" r="0.8" fill="#6B7B3A"/>
  <circle cx="14" cy="10.5" r="0.8" fill="#6B7B3A"/>
  <circle cx="18" cy="10.5" r="0.8" fill="#6B7B3A"/>
  <!-- Water drops falling from pipe -->
  <path d="M7 13 L7 16 Q7 17.5 8 16.5" stroke-opacity="0.6"/>
  <path d="M12 13 L12 17 Q12 18.5 13 17.5" stroke-opacity="0.6"/>
  <path d="M17 13 L17 15.5 Q17 17 18 16" stroke-opacity="0.6"/>
  <!-- Ground/gravel below -->
  <path d="M1 20 Q6 19 12 20 Q18 21 23 20" stroke-opacity="0.4"/>
  <!-- Arrow showing water flow direction -->
  <path d="M3 5 L12 5 L10 3 M12 5 L10 7" stroke-opacity="0.7"/>
</svg>
```

---

### Tools / Hammer Icon

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#6B7B3A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <!-- Hammer handle -->
  <line x1="6" y1="20" x2="14" y2="10"/>
  <!-- Hammer head -->
  <path d="M12 11 L14 8 L20 6 L21 7 L17 12 L14 10 Z"/>
  <!-- Impact lines -->
  <line x1="18" y1="3" x2="19.5" y2="1.5" stroke-opacity="0.5"/>
  <line x1="21" y1="4" x2="23" y2="3.5" stroke-opacity="0.5"/>
  <line x1="20.5" y1="7.5" x2="22.5" y2="7" stroke-opacity="0.5"/>
  <!-- Nail -->
  <line x1="10" y1="6" x2="10" y2="9"/>
  <line x1="8.5" y1="6" x2="11.5" y2="6"/>
</svg>
```

---

### Book / Pages Icon

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#6B7B3A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <!-- Open book - left page -->
  <path d="M12 5 C10 4 7 3 2 3 L2 18 C7 18 10 19 12 20"/>
  <!-- Open book - right page -->
  <path d="M12 5 C14 4 17 3 22 3 L22 18 C17 18 14 19 12 20"/>
  <!-- Spine -->
  <line x1="12" y1="5" x2="12" y2="20"/>
  <!-- Text lines left -->
  <line x1="5" y1="8" x2="10" y2="8" stroke-opacity="0.4"/>
  <line x1="5" y1="11" x2="9" y2="11" stroke-opacity="0.4"/>
  <line x1="5" y1="14" x2="10" y2="14" stroke-opacity="0.4"/>
  <!-- Text lines right -->
  <line x1="14" y1="8" x2="19" y2="8" stroke-opacity="0.4"/>
  <line x1="14" y1="11" x2="19" y2="11" stroke-opacity="0.4"/>
  <line x1="14" y1="14" x2="18" y2="14" stroke-opacity="0.4"/>
</svg>
```

---

### Photo / Camera Icon (for "1200+ photos")

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#6B7B3A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <!-- Camera body -->
  <rect x="2" y="7" width="20" height="13" rx="2"/>
  <!-- Lens bump / viewfinder top -->
  <path d="M8 7 L9 4 L15 4 L16 7"/>
  <!-- Lens circle -->
  <circle cx="12" cy="13.5" r="3.5"/>
  <!-- Inner lens -->
  <circle cx="12" cy="13.5" r="1.5"/>
  <!-- Flash -->
  <circle cx="18" cy="10" r="0.8" fill="#6B7B3A"/>
  <!-- Stack effect (multiple photos) -->
  <path d="M4 21 L20 21" stroke-opacity="0.3"/>
  <path d="M5 22.5 L19 22.5" stroke-opacity="0.15"/>
</svg>
```

---

## Color Reference Quick Sheet

| Token | Hex | Usage |
|---|---|---|
| Olive Green | `#6B7B3A` | Primary brand, icons, buttons |
| Olive Light | `#8B9B5A` | Hover states, light accents |
| Olive Dark | `#5A6A30` | Active states, spine |
| Warm Wood | `#A0845C` | Secondary accents, borders, author name |
| Dark Timber | `#3B3225` | Headings, dark backgrounds, shadows |
| Snow White | `#F5F2EB` | Page background, text on dark |
| Parchment | `#E8E5DE` | Alt section backgrounds |
| Sky Grey | `#D4D8D1` | Subtle borders, muted text |

---

## Notes for Implementation

1. **Image generation order of priority**: Hero background, CTA background, OG image, then problem/solution images. The book mockup and author photo use CSS treatments on real assets.
2. **All generated images should be optimized**: Save as WebP with 80% quality for photographs, SVG for icons. Provide AVIF alternatives for modern browsers.
3. **Responsive considerations**: Hero and CTA backgrounds should be generated at 2560px wide minimum for retina displays. Crop center for mobile.
4. **The CSS fallbacks are designed to be immediately usable** during development before AI images are generated. They use only brand colors and require no external assets.
5. **SVG icons can be colored dynamically** by changing the `stroke` attribute or using `currentColor` instead of the hardcoded hex value for easier theming.
