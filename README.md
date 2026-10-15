# 🏎️ Koenigsegg Gemera (2024) — Photorealistic 3D Model & 12K UHD Pipeline

[![Blender 5.2](https://img.shields.io/badge/Blender-5.2-E87D0D?logo=blender&logoColor=white)](https://www.blender.org/)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Resolution 12K](https://img.shields.io/badge/Render-12K%20UHD%20(11520x6480)-00C853)](#-render-gallery)
[![Resolution 4K](https://img.shields.io/badge/Render-4K%20UHD%20(3840x2160)-00B0FF)](#-render-gallery)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An advanced 3D visualization, procedural modeling, and hyperrealistic texturing project for the **2024 Koenigsegg Gemera** (*Mega-GT*) built inside **Blender 5.2 LTS**. 

This repository features the complete studio scene, custom procedural radial sports tires with dual-tangent PBR normal mapping, authentic Koenigsegg Aircore hollow carbon-fiber wheels, physically accurate tinted glass canopy, and a complete suite of multi-angle presentation renders up to **native 12K UHD (11,520 × 6,480)**.

---

## 📑 Table of Contents
- [Project Highlights](#-project-highlights)
- [Technical Architecture](#-technical-architecture)
  - [Wheel Fitment & Suspension Stance](#1-wheel-fitment--suspension-stance)
  - [Multi-Tangent Dual UV Tire Shader](#2-multi-tangent-dual-uv-tire-shader)
  - [Physically Accurate Glass Canopy](#3-physically-accurate-glass-canopy)
  - [12K Native Tiled Rendering Engine](#4-12k-native-tiled-rendering-engine)
- [Render Gallery](#-render-gallery)
- [Repository Structure](#-repository-structure)
- [How to Use & Render](#-how-to-use--render)
- [Credits & Acknowledgments](#-credits--acknowledgments)

---

## 🌟 Project Highlights

- **Factory-Accurate Staggered Fitment:** Front 21" (`295/30 ZR21`) and rear 22" (`315/30 ZR22`) Koenigsegg Aircore carbon-fiber wheels hugging Michelin sports radial profiles with precise wheel-arch gaps (2.0 cm clearance).
- **Procedural Radial Tires:** Clean 96-segment quad mesh geometry featuring 4 physical longitudinal water evacuation channels (7 mm depth) and dual protective rim flanges.
- **Dual-Tangent PBR Shader:** Resolves the classic UV tangent vector distortion bug by combining two independent `Normal Map` nodes in tangent space mixed via procedural vertex masks.
- **Micro-Grain Rubber Bump:** Fine procedural noise simulating asphalt contact texture with differentiated roughness (satin $0.54$ sidewalls vs. dry-contact $0.84$ tread).
- **Transparent Optical Glass:** Physical glass shader ($IOR = 1.52$) with volumetric light-smoke tinting allowing clear visibility of the 4-seater luxury interior.
- **Native 12K Tiled Rendering Pipeline:** Solves the GPU display buffer limit (`GL_MAX_RENDERBUFFER_SIZE = 8192`) through quadrant camera optical shifts ($f' = 2f$) to render seamless 74.6-Megapixel frames in seconds.

---

## 🔬 Technical Architecture

### 1. Wheel Fitment & Suspension Stance
The chassis stance was calibrated against official Koenigsegg engineering schematics:
- **Ground Clearance:** $11.5\text{ cm}$ front, $12.4\text{ cm}$ rear.
- **Front Axle:** Center at $Z = 0.240\text{ m}$, wheel radius $r_{\text{bead}} = 0.2668\text{ m}$, outer tread $r_{\text{tread}} = 0.3552\text{ m}$, width $295\text{ mm}$.
- **Rear Axle:** Center at $Z = 0.250\text{ m}$, wheel radius $r_{\text{bead}} = 0.2794\text{ m}$, outer tread $r_{\text{tread}} = 0.3739\text{ m}$, width $315\text{ mm}$.
- **Camber:** $-0.8^\circ$ front, $-1.2^\circ$ rear for authentic high-speed stability posture.

### 2. Multi-Tangent Dual UV Tire Shader
To prevent vertical banding caused by mixing normal maps before evaluating tangent vectors:
1. `UVMap_Tread`: 16x circumferential tiling for the directional performance tread pattern.
2. `UVMap_Sidewall`: Radial polar unwrap for manufacturer branding and radial ribbing.
3. **Shader Graph:** Two discrete `ShaderNodeNormalMap` instances evaluate normal vectors in their respective tangent spaces, blended via `ShaderNodeMix (Vector)` using a vertex-attribute mask (`Tread_Mask`), combined with a procedural asphalt micro-texture bump.

### 3. Physically Accurate Glass Canopy
- **Refraction Index:** $IOR = 1.52$ (standard automotive laminated silicate glass).
- **Volumetric Absorption:** Neutral dark smoke absorption coefficient configured so the cabin is visible through the windscreen, roof skylights, and rear engine bay canopy.

### 4. 12K Native Tiled Rendering Engine
Standard viewport rendering at 12K ($11,520 \times 6,480 = 74.65\text{ MP}$) exceeds the hardware renderbuffer limit ($8,192\text{ px}$) of modern GPUs. The included `render_12k_tiled.py` script splits each frame into 4 sub-camera quadrant projections:
$$\text{Focal Length: } f' = 2 \times f_{\text{base}}$$
$$\text{Quadrant Shifts: } (\pm 0.5, \pm 0.28125)$$
Each quadrant ($5,760 \times 3,240$) renders in $\approx 3\text{ seconds}$ and is stitched seamlessly via Pillow without artifacts or edge seams.

---

## 📸 Render Gallery

The full render suite is available in both **4K UHD** and **12K UHD**:

| # | Angle | Resolution | 4K Link | 12K Link |
|---|---|---|---|---|
| **01** | **Hero 3/4 Front** | $11520 \times 6480$ / $3840 \times 2160$ | [4K Preview](renders_4k/01_Gemera_Front_ThreeQuarter_4K.png) | [12K File](renders_12k/01_Gemera_Front_ThreeQuarter_12K.png) |
| **02** | **3/4 Rear Dynamic** | $11520 \times 6480$ / $3840 \times 2160$ | [4K Preview](renders_4k/02_Gemera_Rear_ThreeQuarter_4K.png) | [12K File](renders_12k/02_Gemera_Rear_ThreeQuarter_12K.png) |
| **03** | **Architectural Side Profile** | $11520 \times 6480$ / $3840 \times 2160$ | [4K Preview](renders_4k/03_Gemera_Side_Profile_4K.png) | [12K File](renders_12k/03_Gemera_Side_Profile_12K.png) |
| **04** | **Low-Angle Aggressive Front** | $11520 \times 6480$ / $3840 \times 2160$ | [4K Preview](renders_4k/04_Gemera_Front_Low_Aggressive_4K.png) | [12K File](renders_12k/04_Gemera_Front_Low_Aggressive_12K.png) |
| **05** | **Macro Wheel & Tire Detail** | $11520 \times 6480$ / $3840 \times 2160$ | [4K Preview](renders_4k/05_Gemera_Wheel_Tire_Detail_4K.png) | [12K File](renders_12k/05_Gemera_Wheel_Tire_Detail_12K.png) |
| **06** | **Aerial Cockpit Interior** | $11520 \times 6480$ / $3840 \times 2160$ | [4K Preview](renders_4k/06_Gemera_Aerial_Cockpit_4K.png) | [12K File](renders_12k/06_Gemera_Aerial_Cockpit_12K.png) |
| **07** | **Rear Diffuser & Exhausts** | $11520 \times 6480$ / $3840 \times 2160$ | [4K Preview](renders_4k/07_Gemera_Rear_Diffuser_Low_4K.png) | [12K File](renders_12k/07_Gemera_Rear_Diffuser_Low_12K.png) |

---

## 📁 Repository Structure

```text
├── KOE_Gemera_24_AUTO_SAVE.blend  # Main master studio scene (22.3 MB)
├── scripts/
│   ├── apply_hyperrealistic_tires.py  # Procedural tire generator & dual UV shader
│   ├── batch_render_4k.py             # 7-angle automated 4K renderer
│   ├── render_12k_tiled.py            # Quadrant-based 12K tiled renderer
│   └── send_bpy.py                    # Blender HTTP socket bridge client
├── renders_4k/                        # 7 studio shots in 3840x2160 UHD
│   ├── 01_Gemera_Front_ThreeQuarter_4K.png
│   ├── ...
├── renders_12k/                       # 7 master shots in 11520x6480 (12K UHD)
│   ├── 01_Gemera_Front_ThreeQuarter_12K.png
│   ├── ...
├── tire_textures/                     # Extracted PBR normal & roughness maps
│   ├── sidewall_horizon_nrml_*.dds
│   └── tread_sport_nrml_*.dds
├── .gitignore
└── README.md
```

---

## 🚀 How to Use & Render

### Prerequisites
- **Blender 5.2+**
- **Python 3.10+** (with `Pillow`)

```bash
# Install Pillow for tiled stitching (if rendering 12K)
python -m pip install pillow
```

### Running 12K Batch Renders Headless
```bash
blender -b "KOE_Gemera_24_AUTO_SAVE.blend" --python "scripts/render_12k_tiled.py"
```

### Running 4K Batch Renders
```bash
blender -b "KOE_Gemera_24_AUTO_SAVE.blend" --python "scripts/batch_render_4k.py"
```

---

## 🤝 Credits & Acknowledgments

This project was developed through an advanced collaborative AI engineering workflow:

* **Antigravity (using Flash 3.8):** Autonomous agentic pipeline execution, 3D viewport inspection and spatial verification, mathematical wheel stance and fender clearance calculations, procedural tire mesh builder, dual-tangent normal map shader architecture, and the quadrant-based 12K tiled rendering engine.
* **GPT-6 Astra:** Co-architectural design, asset pipeline integration from vehicle datasets, PBR material logic calibration, and collaborative contributions across the development workflow.
* **Koenigsegg Automotive AB:** Design and engineering inspiration of the Koenigsegg Gemera.
* **Turn 10 Studios:** Reference geometry and texture assets.

---

<p align="center">
  <b>Koenigsegg Gemera 2024</b> — Rendered with Blender 5.2 & Python Automation
</p>
