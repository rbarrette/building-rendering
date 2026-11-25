# Path to the Blender executable (macOS default below; Linux: blender; Windows: "C:/Program Files/Blender Foundation/Blender 4.x/blender.exe")
BLENDER ?= /Applications/Blender.app/Contents/MacOS/Blender
PY      ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
# validate: all layouts unless LAYOUT is given. build/render: LAYOUT defaults to none (shell only).
LB      := $(or $(LAYOUT),none)
# SCAN=0 skips importing reference scans into the .blend (smaller, faster)
SCAN    ?= 1
# ASSETS=0 draws every inventory item as a box (ignores assets/items/*)
ASSETS  ?= 1
# ITEM=<inventory id> for the asset-* targets
ITEM    ?=
# VERSION=<tag> optional version tag for renders/<layout>/versions/
VERSION ?=
# LIGHTING=<plan> SCENE=<scene> from data/lighting.json: photo renders that plan + scene at night
# (renders/<layout>/lighting/<plan>__<scene>__<view>.png). LIGHTING alone just swaps the drawn fixtures.
LIGHTING ?=
SCENE    ?=
# lighting-options: which plans / scenes / views to render for every layout
PLANS        ?= $(shell $(PY) -c "import json;print(' '.join(json.load(open('data/lighting.json'))['plans']))" 2>/dev/null)
SCENES       ?= $(shell $(PY) -c "import json;print(json.load(open('data/lighting.json'))['meta']['default_scene'])" 2>/dev/null)
LIGHT_VIEWS  ?= iso,eye-north
LIGHT_SCALE  ?= 50


.PHONY: lighting-options
.PHONY: setup validate build render photo scan-views asset-import asset-preview scan-import splat-mesh scan-todo all clean

setup:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt

validate:
	$(PY) scripts/validate.py $(if $(LAYOUT),--layout $(LAYOUT),)

build:
	$(BLENDER) --background --python scripts/build_scene.py -- --layout $(LB) $(if $(filter 0,$(SCAN)),--no-scan,) $(if $(filter 0,$(ASSETS)),--no-assets,)

render: build
	$(BLENDER) --background --python scripts/render.py -- --layout $(LB) $(if $(VERSION),--version $(VERSION),)

photo: build  ## textured/lit renders (EEVEE) -> renders/<layout>/photo-*.png ; ENGINE=cycles for path tracing
	$(BLENDER) --background --python scripts/render.py -- --layout $(LB) --look photo --engine $(or $(ENGINE),eevee) $(if $(VERSION),--version $(VERSION),) $(if $(LIGHTING),--lighting $(LIGHTING),) $(if $(SCENE),--scene $(SCENE),)

lighting-options:  ## every layout x lighting plan x scene at night (EEVEE) -> renders/<layout>/lighting/
	@for L in $(basename $(notdir $(wildcard layouts/*.json))); do \
	  $(MAKE) build LAYOUT=$$L SCAN=0 || exit 1; \
	  for P in $(PLANS); do for S in $(SCENES); do \
	    $(BLENDER) --background --python scripts/render.py -- --layout $$L --look photo --lighting $$P --scene $$S --views $(LIGHT_VIEWS) --scale $(LIGHT_SCALE) || exit 1; \
	  done; done; \
	done

scan-views:  ## plan halves + wall elevations of the LiDAR scan with grids -> renders/scan/
	$(MAKE) build LAYOUT=none
	$(BLENDER) --background --python scripts/scan_views.py

asset-import:  ## vendor model -> assets/items/$(ITEM)/$(ITEM).glb + preview. SRC=<file> ARGS="--square --rot 90 ..."
	$(BLENDER) --background --python scripts/asset_tool.py -- import --item $(ITEM) --src $(SRC) $(ARGS)

asset-preview:  ## front/side/top/iso sheet + asset.json for one item -> assets/items/$(ITEM)/
	$(BLENDER) --background --python scripts/asset_tool.py -- preview --item $(ITEM) $(ARGS)

scan-import:  ## item scan -> asset: levels + cuts the floor, drops scraps, 2k textures. SRC=reference/items/$(ITEM)/scan/<file> ARGS="--rot 90 --crop=x0,x1,y0,y1"
	$(BLENDER) --background --python scripts/asset_tool.py -- import --item $(ITEM) --src $(SRC) --scan --square --texture-max 2048 $(ARGS)

splat-mesh:  ## Gaussian-splat PLY -> cleaned vertex-coloured mesh GLB for scan-import. SRC=<splat.ply> OUT=<mesh.glb> ARGS="--keep=... --strip=... --fill=..."
	$(BLENDER) --background --python scripts/splat_mesh.py -- --src $(SRC) $(if $(OUT),--out $(OUT),) $(ARGS)

scan-todo:  ## list inventory items by 3D-scan status (wanted / unset / scanned / not_needed)
	$(PY) scripts/scan_todo.py

all: validate render

clean:
	rm -rf blend/*.blend blend/*.blend1 renders/*/
