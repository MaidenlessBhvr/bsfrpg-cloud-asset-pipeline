# BSFRPG Cloud Asset Pipeline V1

Dedicated script-only Aurelia V4 paving experiment. No game assets or credentials are included.

Rendering is disabled: AURELIA_PILOT_ENABLED=false. Do not dispatch without explicit owner authorization and verified free artifact capacity/paid-usage blocking.

The workflow .github/workflows/aurelia_paving.yml accepts manual dispatch only, uses a standard Ubuntu 24.04 CPU runner, authenticated Ubuntu Blender 4.0.2 packages, two Blender threads and a 15-minute timeout. Outputs are capped at 25 MiB and artifacts retained for one day. No paid GPU or generation APIs are used.

Run local checks from this directory: python cloud_fallback/test_preparation.py and python cloud_fallback/test_ubuntu_preflight.py. These perform layout/validator tests only; do not run Blender locally.

One future authorized run prepares nine neighboring native chunks, world-coordinate metadata, a 32px atlas, a reproducible Blender source and unreviewed previews. Render, seam, repetition, Godot nearest-neighbor and architectural visual QA remain required. Nothing here is production-approved.
